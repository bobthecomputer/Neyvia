use std::{
    collections::HashSet,
    fs::{self, OpenOptions},
    io::Write,
    net::{IpAddr, Ipv4Addr, SocketAddr},
    path::{Path, PathBuf},
    str::FromStr,
    sync::Arc,
    time::Instant,
};

use anyhow::{bail, Context, Result};
use axum::{extract::State, routing::get, Json, Router as AxumRouter};
use futures_lite::StreamExt;
use iroh::{
    endpoint::{presets, AfterHandshakeOutcome, Connection, EndpointHooks},
    protocol::Router as IrohRouter,
    Endpoint, EndpointId, SecretKey,
};
use iroh_blobs::{
    api::{
        blobs::{AddPathOptions, ImportMode},
        remote::GetProgressItem,
    },
    store::fs::FsStore,
    ticket::BlobTicket,
    BlobFormat, BlobsProtocol, Hash,
};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use tokio::{
    io::{AsyncBufReadExt, BufReader},
    net::TcpListener,
};

const SCHEMA: &str = "neyvia.iroh-cache-sidecar/v1";
const VERSION: &str = env!("CARGO_PKG_VERSION");

#[derive(Debug, Deserialize)]
#[serde(tag = "operation", rename_all = "kebab-case")]
enum Request {
    Health,
    Identity {
        #[serde(rename = "stateRoot")]
        state_root: PathBuf,
    },
    Serve {
        #[serde(rename = "stateRoot")]
        state_root: PathBuf,
        #[serde(rename = "storeRoot")]
        store_root: PathBuf,
        sources: Vec<Source>,
        #[serde(rename = "allowedPeers")]
        allowed_peers: Vec<String>,
    },
    Fetch {
        #[serde(rename = "stateRoot")]
        state_root: PathBuf,
        #[serde(rename = "storeRoot")]
        store_root: PathBuf,
        ticket: String,
        #[serde(rename = "objectHash")]
        object_hash: String,
        destination: PathBuf,
        #[serde(rename = "allowedPeers")]
        allowed_peers: Vec<String>,
        #[serde(rename = "maxBytes")]
        max_bytes: u64,
    },
    Session {
        #[serde(rename = "stateRoot")]
        state_root: PathBuf,
        #[serde(rename = "storeRoot")]
        store_root: PathBuf,
        #[serde(rename = "allowedPeers")]
        allowed_peers: Vec<String>,
    },
}

#[derive(Debug, Clone, Deserialize, Serialize)]
struct Source {
    path: PathBuf,
    #[serde(rename = "objectHash")]
    object_hash: String,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
struct ProviderManifest {
    schema: String,
    #[serde(rename = "manifestHash")]
    manifest_hash: String,
    #[serde(rename = "stateRoot")]
    state_root: PathBuf,
    #[serde(rename = "storeRoot")]
    store_root: PathBuf,
    #[serde(rename = "offersPath")]
    offers_path: PathBuf,
    #[serde(rename = "healthPort")]
    health_port: u16,
    sources: Vec<Source>,
    #[serde(rename = "allowedPeers")]
    allowed_peers: Vec<String>,
}

#[derive(Debug, Clone, Serialize)]
struct ProviderHealth {
    schema: &'static str,
    status: &'static str,
    #[serde(rename = "manifestHash")]
    manifest_hash: String,
    objects: usize,
    #[serde(rename = "allowlistedPeers")]
    allowlisted_peers: usize,
    #[serde(rename = "publicDiscovery")]
    public_discovery: bool,
    #[serde(rename = "publicRelay")]
    public_relay: bool,
    #[serde(rename = "endpointIdExposed")]
    endpoint_id_exposed: bool,
    #[serde(rename = "ticketsExposed")]
    tickets_exposed: bool,
}

#[derive(Debug, Deserialize)]
#[serde(tag = "operation", rename_all = "kebab-case")]
enum SessionRequest {
    Health,
    Fetch {
        ticket: String,
        #[serde(rename = "objectHash")]
        object_hash: String,
        destination: PathBuf,
        #[serde(rename = "maxBytes")]
        max_bytes: u64,
    },
    Shutdown,
}

#[derive(Debug, Serialize)]
struct TicketReceipt {
    #[serde(rename = "objectHash")]
    object_hash: String,
    ticket: String,
}

#[derive(Debug)]
struct PeerAllowlist {
    peers: HashSet<EndpointId>,
}

impl PeerAllowlist {
    fn parse(values: &[String]) -> Result<Self> {
        if values.is_empty() {
            bail!("allowedPeers must contain at least one endpoint identity");
        }
        let peers = values
            .iter()
            .map(|value| {
                EndpointId::from_str(value)
                    .with_context(|| format!("invalid allowed endpoint identity: {value}"))
            })
            .collect::<Result<HashSet<_>>>()?;
        Ok(Self { peers })
    }
}

impl EndpointHooks for PeerAllowlist {
    async fn after_handshake<'a>(&'a self, connection: &'a Connection) -> AfterHandshakeOutcome {
        if self.peers.contains(&connection.remote_id()) {
            AfterHandshakeOutcome::Accept
        } else {
            AfterHandshakeOutcome::Reject {
                error_code: 403u32.into(),
                reason: b"endpoint identity is not allowlisted".to_vec(),
            }
        }
    }
}

#[tokio::main]
async fn main() {
    let arguments = std::env::args().skip(1).collect::<Vec<_>>();
    let result = match arguments.as_slice() {
        [] => run().await,
        [flag, path] if flag == "--provider-config" => provider(PathBuf::from(path)).await,
        _ => Err(anyhow::anyhow!(
            "usage: neyvia-iroh-cache [--provider-config ABSOLUTE_PATH]"
        )),
    };
    if let Err(error) = result {
        let payload = json!({
            "schema": SCHEMA,
            "ok": false,
            "status": "error",
            "error": format!("{error:#}"),
        });
        println!("{}", payload);
        std::process::exit(1);
    }
}

async fn run() -> Result<()> {
    let mut lines = BufReader::new(tokio::io::stdin()).lines();
    let line = lines
        .next_line()
        .await?
        .context("one JSON request line is required on stdin")?;
    if line.len() > 1024 * 1024 {
        bail!("request exceeds the 1 MiB control-plane limit");
    }
    let request: Request = serde_json::from_str(&line).context("invalid JSON request")?;
    match request {
        Request::Health => {
            emit(json!({
                "schema": SCHEMA,
                "ok": true,
                "status": "healthy",
                "sidecarVersion": VERSION,
                "irohVersion": "1.0.3",
                "irohBlobsVersion": "0.103.0",
                "controlTransport": "stdin-json-line",
                "publicDiscovery": false,
                "publicRelay": false,
            }))?;
        }
        Request::Identity { state_root } => {
            let secret = load_or_create_secret(&state_root)?;
            emit(json!({
                "schema": SCHEMA,
                "ok": true,
                "status": "identity-ready",
                "endpointId": secret.public().to_string(),
                "secretExposed": false,
            }))?;
        }
        Request::Serve {
            state_root,
            store_root,
            sources,
            allowed_peers,
        } => {
            serve(state_root, store_root, sources, allowed_peers, &mut lines).await?;
        }
        Request::Fetch {
            state_root,
            store_root,
            ticket,
            object_hash,
            destination,
            allowed_peers,
            max_bytes,
        } => {
            fetch(
                state_root,
                store_root,
                ticket,
                object_hash,
                destination,
                allowed_peers,
                max_bytes,
            )
            .await?;
        }
        Request::Session {
            state_root,
            store_root,
            allowed_peers,
        } => {
            session(state_root, store_root, allowed_peers, &mut lines).await?;
        }
    }
    Ok(())
}

async fn serve(
    state_root: PathBuf,
    store_root: PathBuf,
    sources: Vec<Source>,
    allowed_peers: Vec<String>,
    lines: &mut tokio::io::Lines<BufReader<tokio::io::Stdin>>,
) -> Result<()> {
    if sources.is_empty() {
        bail!("serve requires at least one source");
    }
    let allowlist = PeerAllowlist::parse(&allowed_peers)?;
    let secret = load_or_create_secret(&state_root)?;
    let store_root = absolute_directory(&store_root, true)?;
    let store = FsStore::load(&store_root)
        .await
        .context("failed to open the Iroh blob store")?;
    let mut content = Vec::with_capacity(sources.len());
    for source in sources {
        let expected = Hash::from_str(&source.object_hash).context("invalid source objectHash")?;
        let path = absolute_file(&source.path)?;
        let actual = hash_file(&path)?;
        if actual != expected {
            bail!(
                "source hash changed: expected {}, observed {}",
                expected,
                actual
            );
        }
        let imported = store
            .blobs()
            .add_path_with_opts(AddPathOptions {
                path,
                mode: ImportMode::TryReference,
                format: BlobFormat::Raw,
            })
            .with_named_tag(format!("neyvia-{}", expected))
            .await
            .context("failed to import a cache object into the Iroh store")?;
        if imported.hash != expected {
            bail!("Iroh import hash does not match the Neyvia CAS hash");
        }
        content.push(expected);
    }
    let endpoint = Endpoint::builder(presets::Minimal)
        .secret_key(secret)
        .hooks(allowlist)
        .bind()
        .await
        .context("failed to bind the Iroh endpoint")?;
    let blobs = BlobsProtocol::new(&store, None);
    let router = IrohRouter::builder(endpoint)
        .accept(iroh_blobs::ALPN, blobs)
        .spawn();
    let address = router.endpoint().addr();
    let tickets = content
        .iter()
        .map(|hash| TicketReceipt {
            object_hash: hash.to_string(),
            ticket: BlobTicket::new(address.clone(), *hash, BlobFormat::Raw).to_string(),
        })
        .collect::<Vec<_>>();
    emit(json!({
        "schema": SCHEMA,
        "ok": true,
        "status": "serving",
        "endpointId": router.endpoint().id().to_string(),
        "tickets": tickets,
        "allowlistedPeers": allowed_peers.len(),
        "publicDiscovery": false,
        "publicRelay": false,
    }))?;

    let shutdown_line = lines
        .next_line()
        .await?
        .context("serve waits for an explicit shutdown request")?;
    let shutdown: Value = serde_json::from_str(&shutdown_line).context("invalid shutdown JSON")?;
    if shutdown.get("operation").and_then(Value::as_str) != Some("shutdown") {
        bail!("serve accepts only an explicit shutdown request after startup");
    }
    router
        .shutdown()
        .await
        .context("Iroh router shutdown failed")?;
    emit(json!({
        "schema": SCHEMA,
        "ok": true,
        "status": "stopped",
    }))?;
    Ok(())
}

async fn provider(config_path: PathBuf) -> Result<()> {
    let config_path = absolute_file(&config_path)?;
    let raw = fs::read(&config_path)?;
    if raw.len() > 1024 * 1024 {
        bail!("provider manifest exceeds the 1 MiB limit");
    }
    let manifest: ProviderManifest =
        serde_json::from_slice(&raw).context("invalid provider manifest")?;
    if manifest.schema != "neyvia.iroh-provider-manifest/v1" {
        bail!("unsupported provider manifest schema");
    }
    validate_manifest_hash(&manifest)?;
    if manifest.sources.is_empty() {
        bail!("provider manifest must contain at least one source");
    }
    if manifest.health_port < 1024 {
        bail!("healthPort must be between 1024 and 65535");
    }
    let allowlist = PeerAllowlist::parse(&manifest.allowed_peers)?;
    let secret = load_or_create_secret(&manifest.state_root)?;
    let store_root = absolute_directory(&manifest.store_root, true)?;
    let store = FsStore::load(&store_root)
        .await
        .context("failed to open the provider blob store")?;
    let mut content = Vec::with_capacity(manifest.sources.len());
    for source in &manifest.sources {
        let expected = Hash::from_str(&source.object_hash).context("invalid source objectHash")?;
        let path = absolute_file(&source.path)?;
        if hash_file(&path)? != expected {
            bail!("provider source hash changed");
        }
        let imported = store
            .blobs()
            .add_path_with_opts(AddPathOptions {
                path,
                mode: ImportMode::TryReference,
                format: BlobFormat::Raw,
            })
            .with_named_tag(format!("neyvia-{}", expected))
            .await
            .context("failed to import a provider object")?;
        if imported.hash != expected {
            bail!("provider import hash does not match the Neyvia CAS hash");
        }
        content.push(expected);
    }
    let endpoint = Endpoint::builder(presets::Minimal)
        .secret_key(secret)
        .hooks(allowlist)
        .bind()
        .await
        .context("failed to bind the provider endpoint")?;
    let blobs = BlobsProtocol::new(&store, None);
    let iroh_router = IrohRouter::builder(endpoint)
        .accept(iroh_blobs::ALPN, blobs)
        .spawn();
    let address = iroh_router.endpoint().addr();
    let offers = content
        .iter()
        .map(|hash| {
            json!({
                "objectHash": hash.to_string(),
                "ticket": BlobTicket::new(
                    address.clone(),
                    *hash,
                    BlobFormat::Raw,
                ).to_string(),
            })
        })
        .collect::<Vec<_>>();
    atomic_json(
        &manifest.offers_path,
        &json!({
            "schema": "neyvia.iroh-provider-offers/v1",
            "manifestHash": manifest.manifest_hash,
            "endpointId": iroh_router.endpoint().id().to_string(),
            "offers": offers,
            "active": true,
            "credentialMaterial": true,
        }),
    )?;
    let health = Arc::new(ProviderHealth {
        schema: "neyvia.iroh-provider-health/v1",
        status: "healthy",
        manifest_hash: manifest.manifest_hash.clone(),
        objects: content.len(),
        allowlisted_peers: manifest.allowed_peers.len(),
        public_discovery: false,
        public_relay: false,
        endpoint_id_exposed: false,
        tickets_exposed: false,
    });
    let app = AxumRouter::new()
        .route("/health", get(provider_health))
        .with_state(health);
    let listener = TcpListener::bind(SocketAddr::new(
        IpAddr::V4(Ipv4Addr::LOCALHOST),
        manifest.health_port,
    ))
    .await
    .context("failed to bind the provider health endpoint")?;
    axum::serve(listener, app)
        .with_graceful_shutdown(async {
            let _ = tokio::signal::ctrl_c().await;
        })
        .await
        .context("provider health server failed")?;
    iroh_router
        .shutdown()
        .await
        .context("provider router shutdown failed")?;
    Ok(())
}

async fn provider_health(State(health): State<Arc<ProviderHealth>>) -> Json<ProviderHealth> {
    Json((*health).clone())
}

#[allow(clippy::too_many_arguments)]
async fn fetch(
    state_root: PathBuf,
    store_root: PathBuf,
    ticket: String,
    object_hash: String,
    destination: PathBuf,
    allowed_peers: Vec<String>,
    max_bytes: u64,
) -> Result<()> {
    let allowlist = PeerAllowlist::parse(&allowed_peers)?;
    let peers = allowlist.peers.clone();
    let secret = load_or_create_secret(&state_root)?;
    let store_root = absolute_directory(&store_root, true)?;
    let store = FsStore::load(&store_root)
        .await
        .context("failed to open the Iroh download store")?;
    let endpoint = Endpoint::builder(presets::Minimal)
        .secret_key(secret)
        .hooks(allowlist)
        .bind()
        .await
        .context("failed to bind the Iroh endpoint")?;
    let result = fetch_with(
        &store,
        &endpoint,
        &peers,
        ticket,
        object_hash,
        destination,
        max_bytes,
    )
    .await?;
    endpoint.close().await;
    store
        .shutdown()
        .await
        .context("Iroh store shutdown failed")?;
    emit(result)?;
    Ok(())
}

async fn session(
    state_root: PathBuf,
    store_root: PathBuf,
    allowed_peers: Vec<String>,
    lines: &mut tokio::io::Lines<BufReader<tokio::io::Stdin>>,
) -> Result<()> {
    let allowlist = PeerAllowlist::parse(&allowed_peers)?;
    let peers = allowlist.peers.clone();
    let secret = load_or_create_secret(&state_root)?;
    let store_root = absolute_directory(&store_root, true)?;
    let store = FsStore::load(&store_root)
        .await
        .context("failed to open the Iroh session store")?;
    let endpoint = Endpoint::builder(presets::Minimal)
        .secret_key(secret)
        .hooks(allowlist)
        .bind()
        .await
        .context("failed to bind the Iroh session endpoint")?;
    emit(json!({
        "schema": SCHEMA,
        "ok": true,
        "status": "session-ready",
        "endpointId": endpoint.id().to_string(),
        "allowlistedPeers": peers.len(),
        "publicDiscovery": false,
        "publicRelay": false,
    }))?;
    while let Some(line) = lines.next_line().await? {
        if line.len() > 1024 * 1024 {
            emit(error_value("session request exceeds the 1 MiB limit"))?;
            continue;
        }
        let request: SessionRequest = match serde_json::from_str(&line) {
            Ok(value) => value,
            Err(_) => {
                emit(error_value("invalid session JSON request"))?;
                continue;
            }
        };
        match request {
            SessionRequest::Health => emit(json!({
                "schema": SCHEMA,
                "ok": true,
                "status": "session-healthy",
                "endpointId": endpoint.id().to_string(),
                "allowlistedPeers": peers.len(),
            }))?,
            SessionRequest::Fetch {
                ticket,
                object_hash,
                destination,
                max_bytes,
            } => {
                let result = fetch_with(
                    &store,
                    &endpoint,
                    &peers,
                    ticket,
                    object_hash,
                    destination,
                    max_bytes,
                )
                .await;
                match result {
                    Ok(value) => emit(value)?,
                    Err(_) => emit(error_value("session fetch failed"))?,
                }
            }
            SessionRequest::Shutdown => {
                endpoint.close().await;
                store
                    .shutdown()
                    .await
                    .context("Iroh session store shutdown failed")?;
                emit(json!({
                    "schema": SCHEMA,
                    "ok": true,
                    "status": "session-stopped",
                }))?;
                return Ok(());
            }
        }
    }
    endpoint.close().await;
    store
        .shutdown()
        .await
        .context("Iroh session store shutdown failed")?;
    Ok(())
}

async fn fetch_with(
    store: &FsStore,
    endpoint: &Endpoint,
    allowed_peers: &HashSet<EndpointId>,
    ticket: String,
    object_hash: String,
    destination: PathBuf,
    max_bytes: u64,
) -> Result<Value> {
    if max_bytes == 0 {
        bail!("maxBytes must be greater than zero");
    }
    let ticket = BlobTicket::from_str(&ticket).context("invalid blob ticket")?;
    let expected = Hash::from_str(&object_hash).context("invalid objectHash")?;
    if ticket.hash() != expected || ticket.format() != BlobFormat::Raw {
        bail!("ticket content does not match the requested raw object");
    }
    if !allowed_peers.contains(&ticket.addr().id) {
        bail!("ticket provider is not allowlisted");
    }
    let destination = absolute_output(&destination)?;
    let started = Instant::now();
    let connection = endpoint
        .connect(ticket.addr().clone(), iroh_blobs::ALPN)
        .await
        .context("failed to connect to the allowlisted provider")?;
    let mut progress = store
        .remote()
        .fetch(connection, ticket.hash_and_format())
        .stream();
    let stats = loop {
        match progress.next().await {
            Some(GetProgressItem::Progress(downloaded)) if downloaded > max_bytes => {
                bail!("download exceeded maxBytes");
            }
            Some(GetProgressItem::Done(stats)) => break stats,
            Some(GetProgressItem::Error(error)) => return Err(error.into()),
            Some(GetProgressItem::Progress(_)) => {}
            None => bail!("download ended without a final result"),
        }
    };
    store
        .tags()
        .set(format!("neyvia-{}", expected), ticket.hash_and_format())
        .await
        .context("failed to pin the downloaded object")?;
    if destination.exists() {
        bail!("destination already exists");
    }
    let exported = store
        .blobs()
        .export(expected, &destination)
        .await
        .context("failed to export the downloaded object")?;
    if exported > max_bytes {
        let _ = fs::remove_file(&destination);
        bail!("downloaded object exceeds maxBytes");
    }
    let observed = hash_file(&destination)?;
    if observed != expected {
        let _ = fs::remove_file(&destination);
        bail!("exported object failed BLAKE3 verification");
    }
    Ok(json!({
        "schema": SCHEMA,
        "ok": true,
        "status": "fetched",
        "objectHash": expected.to_string(),
        "bytes": exported,
        "wireBytes": stats.total_bytes_read(),
        "durationMs": started.elapsed().as_secs_f64() * 1000.0,
        "integrityVerified": true,
        "providerEndpointId": ticket.addr().id.to_string(),
        "publicDiscovery": false,
        "publicRelay": false,
    }))
}

fn load_or_create_secret(state_root: &Path) -> Result<SecretKey> {
    let state_root = absolute_directory(state_root, true)?;
    let key_path = state_root.join("identity.key");
    if key_path.exists() {
        let metadata = fs::symlink_metadata(&key_path)?;
        if metadata.file_type().is_symlink() || !metadata.is_file() {
            bail!("identity.key must be a regular file, not a link");
        }
        let bytes = fs::read(&key_path)?;
        let value: [u8; 32] = bytes
            .try_into()
            .map_err(|_| anyhow::anyhow!("identity.key must contain exactly 32 bytes"))?;
        return Ok(SecretKey::from_bytes(&value));
    }
    let secret = SecretKey::generate();
    let temporary = state_root.join(format!("identity.key.{}.tmp", std::process::id()));
    let mut file = OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(&temporary)
        .context("failed to create an identity key atomically")?;
    file.write_all(&secret.to_bytes())?;
    file.sync_all()?;
    drop(file);
    fs::rename(&temporary, &key_path).context("failed to activate the identity key")?;
    Ok(secret)
}

fn validate_manifest_hash(manifest: &ProviderManifest) -> Result<()> {
    let mut value = serde_json::to_value(manifest)?;
    let object = value
        .as_object_mut()
        .context("provider manifest must be an object")?;
    object.remove("manifestHash");
    let observed = blake3::hash(&serde_json::to_vec(&value)?)
        .to_hex()
        .to_string();
    if observed != manifest.manifest_hash {
        bail!("provider manifest hash does not match");
    }
    Ok(())
}

fn atomic_json(path: &Path, value: &Value) -> Result<()> {
    let target = absolute_output(path)?;
    let temporary = target.with_file_name(format!(
        ".{}.{}.tmp",
        target
            .file_name()
            .and_then(|value| value.to_str())
            .unwrap_or("offers"),
        std::process::id(),
    ));
    let mut file = OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(&temporary)?;
    serde_json::to_writer(&mut file, value)?;
    file.write_all(b"\n")?;
    file.sync_all()?;
    drop(file);
    fs::rename(&temporary, &target)?;
    Ok(())
}

fn absolute_directory(path: &Path, create: bool) -> Result<PathBuf> {
    if !path.is_absolute() {
        bail!("directory paths must be absolute");
    }
    if create {
        fs::create_dir_all(path)?;
    }
    let canonical = path.canonicalize()?;
    if !canonical.is_dir() {
        bail!("path is not a directory");
    }
    Ok(canonical)
}

fn absolute_file(path: &Path) -> Result<PathBuf> {
    if !path.is_absolute() {
        bail!("source paths must be absolute");
    }
    let metadata = fs::symlink_metadata(path)?;
    if metadata.file_type().is_symlink() || !metadata.is_file() {
        bail!("source must be a regular file, not a link");
    }
    Ok(path.canonicalize()?)
}

fn absolute_output(path: &Path) -> Result<PathBuf> {
    if !path.is_absolute() {
        bail!("destination paths must be absolute");
    }
    let parent = path
        .parent()
        .context("destination must have a parent directory")?;
    fs::create_dir_all(parent)?;
    let parent = parent.canonicalize()?;
    let name = path
        .file_name()
        .context("destination must have a filename")?;
    Ok(parent.join(name))
}

fn hash_file(path: &Path) -> Result<Hash> {
    let mut file = fs::File::open(path)?;
    let mut state = blake3_compat::Hasher::new();
    std::io::copy(&mut file, &mut state)?;
    Ok(Hash::from_bytes(*state.finalize().as_bytes()))
}

fn emit(value: Value) -> Result<()> {
    let mut stdout = std::io::stdout().lock();
    serde_json::to_writer(&mut stdout, &value)?;
    stdout.write_all(b"\n")?;
    stdout.flush()?;
    Ok(())
}

fn error_value(message: &str) -> Value {
    json!({
        "schema": SCHEMA,
        "ok": false,
        "status": "error",
        "error": message,
    })
}

mod blake3_compat {
    use std::io::{self, Write};

    pub struct Hasher(blake3::Hasher);

    impl Hasher {
        pub fn new() -> Self {
            Self(blake3::Hasher::new())
        }

        pub fn finalize(&self) -> blake3::Hash {
            self.0.finalize()
        }
    }

    impl Write for Hasher {
        fn write(&mut self, buffer: &[u8]) -> io::Result<usize> {
            self.0.update(buffer);
            Ok(buffer.len())
        }

        fn flush(&mut self) -> io::Result<()> {
            Ok(())
        }
    }
}
