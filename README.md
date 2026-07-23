# Samsung Eye Comfort Shield → Hyprsunset

This synchronizes Samsung's **Eye Comfort Shield** toggle with Hyprsunset:

- Eye Comfort Shield on → start Hyprsunset if necessary and set the configured
  color temperature.
- Eye Comfort Shield off → apply Hyprsunset's identity transform (no filter).
- PC offline → Tasker keeps publishing a heartbeat; the PC fetches the latest
  cached state when it next starts.
- Connection interruption → the listener reconnects automatically and
  reconciles the current state.

The phone publishes only `on` or `off` to a long, random [ntfy](https://ntfy.sh)
topic. The PC maintains an outbound HTTPS subscription. No router changes,
public PC service, ntfy phone app, or third-party Python packages are needed.

Quickshell is optional. The core listener works on any Hyprland installation
with systemd, and desktop controls can use the small command-line interface.
The project is available under the [MIT License](LICENSE).

## 1. Install the PC listener

Requirements:

- Hyprland 0.45 or newer
- `hyprsunset`, `hyprctl`, Python 3, and systemd

Run:

```bash
chmod +x install.sh uninstall.sh
./install.sh
```

The installer prints a unique **Tasker publish URL**. Keep it private: on the
public ntfy service, possession of this random URL grants read/write access.

The configuration is written to:

```text
~/.config/hyprsunset-sync/config.env
```

The defaults apply 4500 K when enabled and use `identity` when disabled. To
actually kill Hyprsunset on every off event, change `OFF_ACTION=identity` to
`OFF_ACTION=stop`, then run:

```bash
systemctl --user restart hyprsunset-sync.service
```

`identity` is recommended. It is Hyprsunset's supported disable command, removes
the filter immediately, and avoids process churn.

## 2. Install and prepare Tasker on the Galaxy

Install [Tasker](https://play.google.com/store/apps/details?id=net.dinglisch.android.taskerm).
The ntfy Android app is not needed.

On the Samsung phone:

1. Open **Settings → Apps → Tasker → Battery** and choose **Unrestricted**.
2. Open Tasker, accept its requested permissions, and disable Tasker's beginner
   mode if that option is shown.
3. Keep the Tasker publish URL from the installer available for the next steps.

Samsung normally stores the master Eye Comfort Shield toggle as the System
setting `blue_light_filter`. Use Tasker's built-in finder so the phone confirms
that name instead of trusting a firmware assumption:

1. In Tasker, open **Profiles**, press **+**, then choose
   **State → Settings → Custom Setting**.
2. Press the magnifying-glass icon, choose **Find**, toggle Eye Comfort Shield
   once in Samsung Quick Settings, then return to Tasker.
3. Select the detected change. It should show:
   - Type: `System`
   - Name: `blue_light_filter`
   - Value: `1`

If several settings are detected, use the one above. If that key is not offered,
see [Troubleshooting](#troubleshooting).

## 3. Publish state changes from Tasker

After saving the Custom Setting state, Tasker asks for an Enter Task.

Create **ECS On** with one action:

1. **Net → HTTP Request**
2. Method: `POST`
3. URL: the Tasker publish URL printed by `./install.sh`
4. Body: `on`
5. Timeout: `15`

Return to the profile, long-press **ECS On**, choose **Add Exit Task**, and create
**ECS Off** with the same HTTP Request except:

- Body: `off`

Test from Samsung Quick Settings. On the PC, watch:

```bash
journalctl --user -u hyprsunset-sync.service -f
```

## 4. Add the offline-resync heartbeat

ntfy's public cache is temporary. A small Tasker heartbeat ensures the latest
state remains available no matter how long the PC is off.

Create these two additional profiles:

### ECS heartbeat on

1. Add a **Time** profile from `00:00` to `23:59`, repeating every **4 hours**.
2. Long-press its Time context, choose **Add → State → Settings → Custom
   Setting**.
3. Set Type `System`, Name `blue_light_filter`, Value `1`.
4. Use the existing **ECS On** task.

### ECS heartbeat off

1. Clone the heartbeat-on profile.
2. Edit its Custom Setting state and enable **Invert**.
3. Use **ECS Off** as its task.

Only one heartbeat profile matches at a time. Four-hour publishing is negligible
for battery and keeps the state inside ntfy's cache window.

## Verification

Validate local requirements:

```bash
~/.local/bin/hyprsunset-sync --check
```

Publish test states from the PC itself:

```bash
source ~/.config/hyprsunset-sync/config.env
curl --data on  "$NTFY_BASE_URL/$NTFY_TOPIC"
curl --data off "$NTFY_BASE_URL/$NTFY_TOPIC"
```

Check service state and recent logs:

```bash
systemctl --user status hyprsunset-sync.service
journalctl --user -u hyprsunset-sync.service -n 50 --no-pager
```

## Desktop controls

The installed command also provides a small control interface:

```bash
hyprsunset-sync --status
hyprsunset-sync --set on
hyprsunset-sync --set off
hyprsunset-sync --set toggle
```

`--set` applies the change locally first and then publishes it to the shared
topic. It therefore remains usable if the internet is temporarily unavailable.
The status is persisted under `~/.local/state/hyprsunset-sync/`, so a panel can
display the correct state after being reloaded.

For Quickshell, poll `hyprsunset-sync --status` and bind the button to
`hyprsunset-sync --set toggle`. Do not launch or kill `hyprsunset` directly from
the panel; doing that creates a competing daemon and bypasses synchronization.

The reusable `NightLightSync.qml` controller can be installed without changing
any existing panel files:

```bash
./install-quickshell.sh
```

Pass `--component-dir PATH` when your components live somewhere other than the
Quickshell configuration root. See [the generic Quickshell integration
guide](docs/quickshell.md) for the binding API and an example button.

The optional `--auto-patch` flag only supports the specific `panel/ToggleGrid.qml`
layout included in this repository's patch example. It checks for that layout
and creates `ToggleGrid.qml.pre-hyprsunset-sync` before changing it. Other
Quickshell configurations remain untouched.

## Install on another PC

Clone the repository on the other Hyprland/Quickshell machine, then run the
same installer. Use the **same** `config.env` on both computers so they read
the same ntfy topic.

```bash
git clone https://github.com/TheWoomy27/hyprsunset-sync.git
cd hyprsunset-sync
mkdir -p ~/.config/hyprsunset-sync
# Securely transfer the desktop's config.env to this location.
install -m600 /path/from-desktop/config.env ~/.config/hyprsunset-sync/config.env
./install-quickshell.sh --auto-patch
```

If the laptop has not yet been configured, run `./install.sh` once to generate
its config, then replace its `NTFY_BASE_URL`, `NTFY_TOPIC`, `TEMPERATURE`, and
optional `NTFY_TOKEN` values with the values from the desktop's
`~/.config/hyprsunset-sync/config.env`. Keep that file private; it must never
be committed to Git.

## Troubleshooting

### Tasker does not detect `blue_light_filter`

The setting name is Samsung-specific and can change between One UI builds. Run
Tasker's Custom Setting finder again and toggle only Eye Comfort Shield during
the detection window. Use the System setting whose value changes between `0`
and `1`.

If Tasker can see the setting but cannot monitor it, connect the phone to ADB
once and grant Tasker secure-settings access:

```bash
adb shell pm grant net.dinglisch.android.taskerm android.permission.WRITE_SECURE_SETTINGS
```

Reading the Samsung System setting normally does not require this grant; use it
only if Tasker reports a permission failure.

### The PC receives state but the screen does not change

Confirm Hyprsunset works independently:

```bash
hyprctl hyprsunset temperature 4500
hyprctl hyprsunset identity
```

If the first command says the Hyprsunset socket is unavailable:

```bash
systemctl --user enable --now hyprsunset.service
```

### Use an authenticated or self-hosted ntfy server

Set `NTFY_BASE_URL`, `NTFY_TOPIC`, and optionally `NTFY_TOKEN` in
`~/.config/hyprsunset-sync/config.env`. For an authenticated server, also add
this header to both Tasker HTTP actions:

```text
Authorization:Bearer YOUR_TOKEN
```

Restart the listener after editing its configuration.

## Removal

```bash
./uninstall.sh
```

The uninstaller deliberately retains the private configuration file.
