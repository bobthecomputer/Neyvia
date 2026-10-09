# My Neyvia app

Copy this folder to your app source. Set the unique instance ID in `neyvia.app.json` and `www/app.js`; keep the owner/provider/memory/CL clients in `neyvia-sdk`. Install the folder in Marketplace → Apps & mods, inspect its manual/contracts, enable it and open the hosted app. Connect proves the shared provider-status call with your Neyvia sign-in.

For richer typed state, persistence and mobile exports, use the existing `app_sdk.new` generator. Do not copy its server/reducer architecture into another framework. The full reuse guide is [Building apps and mods](../../docs/BUILDING_APPS_AND_MODS.md).
