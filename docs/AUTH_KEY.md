# Pairing key setup

Bracer authenticates with the band's existing 16-byte pairing key, written as 32 hexadecimal characters. A Zepp browser `app_token` is a separate account session token used only during retrieval; Bracer does not need it to connect over Bluetooth.

## Browser-session route used during setup

This route worked during the original setup with a Google login. It is a historical result, not a guarantee that every account, region, or app version exposes the same record.

1. Keep the band paired and synced in Zepp Life.
2. Sign into [Zepp's watchface site](https://watchface.zepp.com) with the same account.
3. The setup used browser login cookies (`hm-user-login-info`, or separate `userid` and `apptoken`) to obtain the account ID and session token locally.
4. An authenticated browser request to `GET https://api-mifit-us3.zepp.com/users/<user_id>/devices` returned device records. Match the band's Bluetooth address, parse its `additionalInfo` JSON, and extract `auth_key`.
5. Save only the matching key in local `auth-key.txt`, protect it with `chmod 600 auth-key.txt`, then import it:

   ```sh
   .venv/bin/python -m miband_agent setup --address AA:BB:CC:DD:EE:FF --key-file auth-key.txt
   ```

6. Delete the extra key file if no longer needed and log out of the watchface site. Do not save browser cookies, tokens, or full device responses in the repo.

The successful browser snippet itself was not retained in this repository. Refer to [Gadgetbridge's Huami/Xiaomi key guide](https://gadgetbridge.org/basics/pairing/huami-xiaomi-server/) for the retrieval procedure rather than inventing cookies or request headers.

## Empty lists and login differences

A successful login does not establish that the backend contains the key. Confirm the correct account, binding, recent sync, and regional host. The watchface/Zepp backend and Zepp Life records can differ. The original account helper requested `appname: com.xiaomi.hm.health`; a Gadgetbridge browser example used `com.huami.midong`. Substituting headers was only a diagnostic possibility, not a confirmed fix for an empty list.

Password-based account tools did not work with the Google login used during setup. The phone proxy reached the app's traffic, but Zepp Life rejected its certificate, so no key was captured. See [experimental helpers](KEY_CAPTURE.md) for the retained tools and limitations.

## Key lifetime and storage

Normal disconnects and restarts keep the existing pairing usable. Unbinding, factory resetting, or re-pairing requires retrieving the new key, rerunning `setup`, and restarting the service. Keep phone Bluetooth off while Bracer owns the band.

The default `.env` contains `MIBAND_ADDRESS` and `MIBAND_AUTH_KEY`, plus optional `ZEPP_EMAIL` and `ZEPP_PASSWORD` for the experimental account helper. It is ignored by Git and written with mode `0600`. The service reads it on startup, so restart after changing it. Keys previously shared in chat should be treated as exposed; re-pairing rotates the band key.
