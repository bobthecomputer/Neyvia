/* Shared Babylon implementation: browser uses Engine; native proof uses NullEngine.
 * No simulated scene data. Every observation is read from Babylon scene objects.
 */
(function (scope) {
  class NeyviaScene {
    constructor(B, engine, options = {}) {
      this.B = B; this.engine = engine; this.options = options;
      this.scene = new B.Scene(engine); this.scene.clearColor = new B.Color4(.06,.085,.1,1);
      this.camera = new B.ArcRotateCamera('Editor camera', -Math.PI/2, Math.PI/3, 9, B.Vector3.Zero(), this.scene);
      this.light = new B.HemisphericLight('Sky', new B.Vector3(0,1,0), this.scene);
      this.selected = null; this.running = false; this.revision = 0; this.logs = [];
      this.savedHash = null;
      this.scene.onBeforeRenderObservable.add(() => {
        if (this.running) for (const mesh of this.scene.meshes) if (mesh.metadata?.spin) mesh.rotation.y += .015;
      });
    }
    /* The studio scene a new project opens on: a ground with a grid, a key light that casts soft
     * shadows, a fill from the sky, and three real meshes to look at and select. They are ordinary
     * scene objects (inspect lists them; edits and saves treat them like any other). */
    seedStudio(look = 'dark') {
      const B = this.B, scene = this.scene;
      const cam = this.camera;
      cam.alpha = -Math.PI * 0.62; cam.beta = Math.PI * 0.36; cam.radius = 10.5; cam.target = new B.Vector3(0, 0.85, 0);
      cam.lowerRadiusLimit = 3; cam.upperRadiusLimit = 40; cam.lowerBetaLimit = 0.15; cam.upperBetaLimit = Math.PI * 0.49; cam.minZ = 0.05;
      if ('wheelDeltaPercentage' in cam) cam.wheelDeltaPercentage = 0.01;
      this.light.intensity = 0.6;
      const sun = new B.DirectionalLight('Sun', new B.Vector3(-0.55, -1, 0.42), scene);
      sun.position = new B.Vector3(6, 11, -5); sun.intensity = 1.05;
      let shadows = null;
      try { shadows = new B.ShadowGenerator(1024, sun); shadows.useBlurExponentialShadowMap = true; shadows.blurKernel = 24; shadows.setDarkness?.(0.25); } catch { shadows = null; }
      const paint = (mesh, rgb, specular = 0.18, power = 48) => {
        const material = new B.StandardMaterial(mesh.name + '-material', scene);
        material.diffuseColor = new B.Color3(...rgb); material.specularColor = new B.Color3(specular, specular, specular); material.specularPower = power;
        mesh.material = material; mesh.receiveShadows = true; mesh.metadata = {spin: false};
        shadows?.addShadowCaster(mesh);
        return mesh;
      };
      const ground = B.MeshBuilder.CreateGround('Ground', {width: 16, height: 16}, scene);
      paint(ground, [0.3, 0.31, 0.33], 0, 1); ground.isPickable = false;
      const lines = [];
      for (let i = -8; i <= 8; i += 1) { lines.push([new B.Vector3(i, 0.003, -8), new B.Vector3(i, 0.003, 8)]); lines.push([new B.Vector3(-8, 0.003, i), new B.Vector3(8, 0.003, i)]); }
      const grid = B.MeshBuilder.CreateLineSystem('Grid', {lines}, scene);
      grid.isPickable = false; grid.metadata = {spin: false};
      const knot = paint(B.MeshBuilder.CreateTorusKnot('Torus knot', {radius: 0.82, tube: 0.26, radialSegments: 180, tubularSegments: 28}, scene), [0.3, 0.56, 0.96], 0.45, 72);
      knot.position.y = 1.55; knot.metadata = {spin: true};
      const sphere = paint(B.MeshBuilder.CreateSphere('Sphere', {diameter: 1.15, segments: 48}, scene), [0.93, 0.91, 0.87], 0.3, 64);
      sphere.position.set(-2.4, 0.575, 0.9);
      const cube = paint(B.MeshBuilder.CreateBox('Cube', {size: 1}, scene), [0.86, 0.46, 0.33], 0.12, 32);
      cube.position.set(2.3, 0.5, -0.6); cube.rotation.y = 0.5;
      this.setLook(look);
      return this.observe();
    }
    /* Light or dark studio: the clear colour, the haze that fades the floor into it, the floor and grid. */
    setLook(look = 'dark') {
      const B = this.B, scene = this.scene, light = look === 'light';
      const sky = light ? [0.905, 0.915, 0.93] : [0.112, 0.12, 0.135];
      scene.clearColor = new B.Color4(...sky, 1);
      scene.fogMode = B.Scene.FOGMODE_EXP2; scene.fogDensity = 0.045; scene.fogColor = new B.Color3(...sky);
      if (this.light) this.light.groundColor = light ? new B.Color3(0.62, 0.64, 0.68) : new B.Color3(0.16, 0.17, 0.2);
      const ground = scene.getMeshByName('Ground');
      if (ground?.material?.diffuseColor) ground.material.diffuseColor = light ? new B.Color3(0.84, 0.85, 0.87) : new B.Color3(0.3, 0.31, 0.33);
      const grid = scene.getMeshByName('Grid');
      if (grid) { grid.color = light ? new B.Color3(0.45, 0.48, 0.53) : new B.Color3(0.62, 0.66, 0.72); grid.alpha = light ? 0.28 : 0.16; }
      this.look = light ? 'light' : 'dark';
    }
    finite(value, length) {
      if (!Array.isArray(value) || value.length !== length || !value.every(v => Number.isFinite(v))) throw Error('Expected finite vector of length ' + length);
      return value;
    }
    mesh(name) {
      const matches = this.scene.meshes.filter(mesh => mesh.name === name);
      if (matches.length !== 1) throw Error(matches.length ? 'Mesh name is ambiguous: ' + name : 'No mesh named ' + name);
      return matches[0];
    }
    observe() {
      return {nativeEngine: this.options.headless ? 'Babylon NullEngine' : 'Babylon WebGL Engine',
        revision: this.revision, running: this.running, selected: this.selected, fps: this.engine.getFps(),
        meshes: this.scene.meshes.map(m => ({name:m.name,uniqueId:m.uniqueId,parent:m.parent?.name||null,position:m.position.asArray(),rotation:m.rotation.asArray(),
          scaling:m.scaling.asArray(),vertices:m.getTotalVertices(),enabled:m.isEnabled(),
          color:m.material?.diffuseColor?.asArray() || null})), console:this.logs.slice(-40)};
    }
    async persist() {
      if (this.options.persist) {
        this.scene.metadata = {...(this.scene.metadata || {}),neyviaRevision:this.revision};
        const saved = await this.options.persist(JSON.stringify(this.B.SceneSerializer.Serialize(this.scene)), this.savedHash);
        this.savedHash = saved.sha256;
      }
    }
    async dispatch(action, args = {}) {
      const B = this.B;
      if (action === 'inspect') return this.observe();
      if (action === 'console') return {messages:this.logs.slice(-100)};
      if (action === 'select') {this.selected = this.mesh(args.name).name; return this.observe();}
      if (action === 'edit') {
        if (args.expectedRevision != null && args.expectedRevision !== this.revision) throw Error('Scene revision changed; inspect again');
        if (this.options.beforeMutate) await this.options.beforeMutate(this.savedHash);
        for (const key of ['position','rotation','scaling','color']) if (args[key] != null) this.finite(args[key],3);
        if (args.op === 'create') {
          if (typeof args.name !== 'string' || !args.name || args.name.length > 100 || this.scene.getMeshByName(args.name)) throw Error('Choose a new mesh name');
          if (this.scene.meshes.length >= 2000) throw Error('Scene mesh limit reached');
          const shape = args.shape || 'box';
          if (!['box','sphere','ground'].includes(shape)) throw Error('Unsupported primitive');
          const mesh = shape === 'sphere' ? B.MeshBuilder.CreateSphere(args.name, {diameter:1}, this.scene)
            : shape === 'ground' ? B.MeshBuilder.CreateGround(args.name, {width:6,height:6}, this.scene)
            : B.MeshBuilder.CreateBox(args.name, {size:1}, this.scene);
          mesh.material = new B.StandardMaterial(args.name + '-material',this.scene);
          mesh.material.diffuseColor = new B.Color3(.25,.65,.5);
          mesh.metadata = {spin:false}; this.selected = mesh.name;
        } else if (!['transform','material'].includes(args.op)) throw Error('Unsupported edit operation');
        const mesh = this.mesh(args.name || this.selected);
        // Validate all requested values before changing any existing mesh property.
        for (const key of ['position','rotation','scaling','color']) if (args[key] != null) this.finite(args[key],3);
        for (const key of ['position','rotation','scaling']) if (args[key]) mesh[key].copyFromFloats(...args[key]);
        if (args.color) {
          if (!mesh.material) mesh.material = new B.StandardMaterial(mesh.name+'-material',this.scene);
          mesh.material.diffuseColor = new B.Color3(...args.color);
        }
        if (args.spin != null) mesh.metadata = {...(mesh.metadata || {}),spin:args.spin === true};
        this.revision++; await this.persist(); this.scene.render(); return this.observe();
      }
      if (action === 'run' || action === 'stop') {this.running = action === 'run'; this.scene.render(); return this.observe();}
      if (action === 'interact') {
        if (this.options.beforeMutate) await this.options.beforeMutate(this.savedHash);
        const mesh = this.mesh(args.name || this.selected);
        if (!Number.isFinite(args.rotateY)) throw Error('Supply finite rotateY radians');
        mesh.rotation.y += args.rotateY; this.selected = mesh.name; this.revision++;
        this.scene.render(); await this.persist(); return this.observe();
      }
      if (action === 'test') {
        const mesh = this.mesh(args.name); const checks = [];
        if (args.position) checks.push({check:'position',passed:JSON.stringify(mesh.position.asArray()) === JSON.stringify(this.finite(args.position,3))});
        if (args.minVertices != null) checks.push({check:'vertices',passed:mesh.getTotalVertices() >= args.minVertices});
        if (!checks.length) throw Error('Supply a behavioral assertion');
        if (checks.some(c => !c.passed)) throw Error('Scene assertion failed: ' + JSON.stringify(checks));
        return {passed:true,checks,observation:this.observe()};
      }
      if (action === 'export') {
        if (!this.options.exportAsset) throw Error('Export destination is not configured');
        const gltf = await B.GLTF2Export.GLBAsync(this.scene, 'scene', {shouldExportNode:n=>n instanceof B.Mesh});
        const file = gltf.glTFFiles['scene.glb'];
        const bytes = new Uint8Array(await file.arrayBuffer());
        return await this.options.exportAsset(args.path || args.outputPath, bytes, args.expectedSha256);
      }
      if (action === 'load_asset') {
        if (!this.options.loadAsset) throw Error('Asset loader is not configured');
        if (this.options.beforeMutate) await this.options.beforeMutate(this.savedHash);
        const result = await this.options.loadAsset(args.path || args.assetPath, this.scene);
        for (const mesh of result.meshes) if (this.scene.meshes.filter(m=>m.name===mesh.name).length > 1) mesh.name += ' (import ' + mesh.uniqueId + ')';
        this.revision++; await this.persist();
        return {loaded:result.meshes.map(m=>m.name),observation:this.observe()};
      }
      throw Error('Unsupported Babylon action: ' + action);
    }
  }
  scope.NeyviaScene = NeyviaScene;
  if (typeof module !== 'undefined') module.exports = NeyviaScene;
})(typeof globalThis !== 'undefined' ? globalThis : this);
