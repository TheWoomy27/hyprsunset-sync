# Quickshell integration

Quickshell is optional. `hyprsunset-sync` runs as a user service and can be used
without any panel.

## Install the reusable controller

Install the core service and copy `NightLightSync.qml` into the root of the
default Quickshell configuration:

```bash
./install-quickshell.sh
```

If your QML components live in another directory, specify it:

```bash
./install-quickshell.sh \
  --component-dir "$HOME/.config/quickshell/components"
```

The installer does not modify or restart the panel. Reload Quickshell using the
method appropriate for that configuration after adding the binding.

## Bind any button

Instantiate the non-visual controller beside the button:

```qml
NightLightSync {
    id: nightLight
}
```

Bind the panel's active appearance and click handler:

```qml
active: nightLight.active
onClicked: nightLight.toggle()
```

The public interface is:

- `active`: current synchronized on/off state
- `busy`: whether a local state change is being processed
- `toggle()`: invert the state
- `refresh()`: read the state immediately

The controller also refreshes itself every three seconds, so changes originating
from the phone or another computer appear in the panel.

## Minimal standard-QtQuick example

This example does not depend on a custom toggle component:

```qml
import QtQuick

Item {
    width: 140
    height: 48

    NightLightSync {
        id: nightLight
    }

    Rectangle {
        anchors.fill: parent
        radius: 10
        color: nightLight.active ? "#7cafff" : "#1e2030"

        Text {
            anchors.centerIn: parent
            text: nightLight.active ? "Night Light: On" : "Night Light: Off"
            color: nightLight.active ? "#191a2a" : "#c8d3f5"
        }

        MouseArea {
            anchors.fill: parent
            enabled: !nightLight.busy
            onClicked: nightLight.toggle()
        }
    }
}
```

## Compatible ToggleGrid auto-patch

For the panel layout whose legacy toggle directly starts and kills Hyprsunset,
the repository includes an opt-in patch:

```bash
./install-quickshell.sh --auto-patch
```

The patch is deliberately not applied by default. It only targets
`~/.config/quickshell/panel/ToggleGrid.qml`, verifies the expected lines, and
keeps a `.pre-hyprsunset-sync` backup.

## Other panels

Any panel or launcher that can execute commands can use:

```bash
hyprsunset-sync --status
hyprsunset-sync --set toggle
hyprsunset-sync --set on
hyprsunset-sync --set off
```

Temperature and off behavior belong in
`~/.config/hyprsunset-sync/config.env`; panel integrations should not start or
kill `hyprsunset` themselves.
