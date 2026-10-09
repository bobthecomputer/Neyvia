# Hermes Claude subscription connection

## Experimental subscription provider (2026-09-29)

Provider connections now has a separate **Claude subscription · Hermes** panel.
It checks the installed Hermes version, catalog plugin metadata, and official
Claude CLI auth status. Installation and login open the vendor CLIs on the
backend host. No credentials are copied into Neyvia. Enabling requires local
prerequisites and an explicit experimental-route acknowledgement; disable is
available from the same panel. This is Hermes orchestration, not a new Neyvia
native model client.

The chat provider `claude-subscription-directsdk-experimental` selects Hermes
and defaults to `sonnet`. Before launching, Neyvia checks readiness again,
rejects conflicting credential/endpoint overrides and configured model
fallbacks or auxiliary providers, and prevents Neyvia runtime fallback. It does
not change the account's extra-usage setting, promise included usage for every
model, or intercept/modify Claude's HTTP traffic. The third-party plugin itself
uses a request-scoped relay as described in its documentation.

Account safety is **not certified**. Anthropic's SDK billing notice says the
announced billing change is paused, while its login/developer guidance restricts
third-party subscription routing and identity misrepresentation. These are not
an explicit approval of this specific plugin. Do not market it as approved or
ban-free, silently enable it, pool accounts, or bypass service refusals/limits.
Users requiring an approved distribution route should use API/cloud auth or
obtain clarification from Anthropic.

- [Anthropic account and developer guidance](https://support.claude.com/en/articles/13189465-log-in-to-your-claude-account)
- [Anthropic SDK billing notice](https://support.claude.com/en/articles/15036540-use-the-claude-agent-sdk-with-your-claude-plan)
- [Hermes plugin and requirements](https://hermes-agent.nousresearch.com/docs/plugins/claude-subscription-directsdk)

The installed Hermes is **0.21.3**, below the plugin's **0.21.4** requirement.
The actual UI and backend reject installation, login and activation on that
runtime before a model request is made. No plugin was installed or generation
tested, and the customized Hermes checkout was not upgraded. Production use
remains unverified until a compatible runtime and account eligibility are
established. Evidence: `proof/claude-subscription-20260929/`.

## Legacy extra-credit connection

Neyvia's provider connection queue has a separate **Hermes / Claude Max** route.
It delegates sign-in to Hermes itself by opening a terminal on the Neyvia backend
host and running:

```text
hermes auth add anthropic --type oauth --label neyvia-claude-subscription
```

The one-time authorization code stays in the Hermes terminal. Hermes stores and
refreshes the credential in its private auth store. Neyvia checks only the
redacted result of `hermes auth status anthropic`; it never reads, copies,
returns, or relays the credential. Chat turns must select the Hermes runtime and
the Anthropic provider to use this route. It does not change Claude Code login or
Neyvia's Anthropic-compatible proxy policy.

## Account and billing requirements

Hermes' installed documentation states that native Anthropic OAuth requires a
Claude Max plan with purchased extra-usage credits. Hermes' Anthropic OAuth
requests consume those extra credits; the included Max allowance is not used.
Claude Pro does not support this OAuth route. Use an Anthropic API key or an
approved enterprise route if that is the account setup instead. Plan eligibility
and usage are controlled by Anthropic and can change; Neyvia does not infer
eligibility from a successful login.

The connection status means Hermes reports an Anthropic login. It does not prove
that a particular subscription tier is eligible, that a model is enabled, or
that a request will succeed. A real Hermes turn is the final route proof.

## Installed runtime evidence

The development Hermes runtime reports version `0.21.3` and exposes
`hermes auth add <provider> --type oauth`. Its local provider documentation names
the Anthropic OAuth path and the Max plus extra-usage requirement. Hermes' online
provider guide documents the same flow and the usage limits:

- [Hermes Agent provider setup](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/integrations/providers.md)
- [Hermes Agent credential pools](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/features/credential-pools.md)
