# Bluetooth GATT SDK for Python
The Bluetooth GATT SDK for Python helps you implementing and communicating with any Bluetooth Low Energy device that has a GATT profile. As of now it supports:

* Discovering nearby Bluetooth Low Energy devices
* Connecting and disconnecting devices
* Implementing your custom GATT profile
* Accessing all GATT services
* Accessing all GATT characteristics
* Reading characteristic values
* Writing characteristic values
* Subscribing for characteristic value change notifications

Currently Linux is the only platform supported by this library. Unlike other libraries this GATT SDK is based directly on the mature and stable D-Bus API of BlueZ to interact with Bluetooth devices. In the future we would like to make this library platform-independent by integrating with more Bluetooth APIs of other operating systems such as MacOS and Windows.

## Prerequisites
The GATT SDK requires [Python 3.4+](https://www.python.org). Currently Linux is the only supported operating system and therefor it needs a recent installation of [BlueZ](http://www.bluez.org/). It is tested to work fine with BlueZ 5.44, slightly older versions should however work, too.

## Installation
These instructions assume a Debian-based Linux.

On Linux the [BlueZ](http://www.bluez.org/) library is necessary to access your built-in Bluetooth controller or Bluetooth USB dongle. Some Linux distributions provide a more up-to-date BlueZ package, some other distributions only install older versions that don't implement all Bluetooth features needed for this SDK. In those cases you want to either update BlueZ or build it from sources.

### Updating/installing BlueZ via apt-get

1. `bluetoothd --version` Obtains the version of the pre-installed BlueZ. `bluetoothd` daemon must run at startup to expose the Bluetooth API via D-Bus.
2. `sudo apt-get install --no-install-recommends bluetooth` Installs BlueZ
3. If the installed version is too old, proceed with next step: [Installing BlueZ from sources](#installing-bluez-from-sources)

### Installing BlueZ from sources

The `bluetoothd` daemon provides BlueZ's D-Bus interfaces that is accessed by the GATT SDK to communicate with Bluetooth devices. The following commands download BlueZ 5.44 sources, built them and replace any pre-installed `bluetoothd` daemon. It's not suggested to remove any pre-installed BlueZ package as its deinstallation might remove necessary Bluetooth drivers as well.

1. `sudo systemctl stop bluetooth`
2. `sudo apt-get update`
3. `sudo apt-get install libusb-dev libdbus-1-dev libglib2.0-dev libudev-dev libical-dev libreadline-dev libdbus-glib-1-dev unzip`
4. `cd`
5. `mkdir bluez`
6. `cd bluez`
7. `wget http://www.kernel.org/pub/linux/bluetooth/bluez-5.44.tar.xz`
8. `tar xf bluez-5.44.tar.xz`
9. `cd bluez-5.44`
10. `./configure --prefix=/usr --sysconfdir=/etc --localstatedir=/var --enable-library`
11. `make`
12. `sudo make install`
13. `sudo ln -svf /usr/libexec/bluetooth/bluetoothd /usr/sbin/`
14. `sudo install -v -dm755 /etc/bluetooth`
15. `sudo install -v -m644 src/main.conf /etc/bluetooth/main.conf`
16. `sudo systemctl daemon-reload`
17. `sudo systemctl start bluetooth`
18. `bluetoothd --version` # should now print 5.44

Please note that some distributions might use a different directory for system deamons, apply step 13 only as needed.

### Enabling your Bluetooth adapter

1. `echo "power on" | sudo bluetoothctl` Enables your built-in Bluetooth adapter or external Bluetooth USB dongle

### Using BlueZ commandline tools
BlueZ also provides an interactive commandline tool to interact with Bluetooth devices. You know that your BlueZ installation is working fine if it discovers any Bluetooth devices nearby.

`sudo bluetoothctl` Starts an interactive mode to talk to BlueZ
  * `power on` Enables the Bluetooth adapter
  * `scan on` Start Bluetooth device scanning and lists all found devices with MAC addresses
  * `connect AA:BB:CC:DD:EE:FF` Connects to a Bluetooth device with specified MAC address
  * `exit` Quits the interactive mode

### Installing GATT SDK for Python

To install this GATT module globally, run:

```
sudo pip3 install gatt
```

#### Running the GATT control script

To test if your setup is working, run the `gattctl` tool that is part of this SDK. Note that it must be run as root because on Linux, Bluetooth discovery by default is a restricted operation.

```
sudo gattctl --discover
sudo gattctl --connect AA:BB:CC:DD:EE:FF # Replace the MAC address with your Bluetooth device's MAC address
sudo gattctl --help # To list all available commands
```

## SDK Usage

This SDK requires you to create subclasses of `gatt.DeviceManager` and `gatt.Device`. The other two classes `gatt.Service` and `gatt.Characteristic` are not supposed to be subclassed.

`gatt.DeviceManager` manages all known Bluetooth devices and provides a device discovery to discover nearby Bluetooth Low Energy devices. You want to subclass this manager to access Bluetooth devices as they are discovered as well as to restrict the set of devices to those that you actually want to support by your manager implementation. By default `gatt.DeviceManager` discovers and returns all Bluetooth devices but you can restrict that by overriding `gatt.DeviceManager.make_device()`.

`gatt.Device` is the base class for your Bluetooth device. You will need to subclass it to implement the Bluetooth GATT profile of your choice. Override `gatt.Device.services_resolved()` to interact with the GATT profile, i.e. start reading from and writing to characteristics or subscribe to characteristic value change notifications.

### Discovering nearby Bluetooth Low Energy devices

The SDK entry point is the `DeviceManager` class. Check the following example to dicover any Bluetooth Low Energy device nearby.

```python
import gatt

class AnyDeviceManager(gatt.DeviceManager):
    def device_discovered(self, device):
        print("Discovered [%s] %s" % (device.mac_address, device.alias()))

manager = AnyDeviceManager(adapter_name='hci0')
manager.start_discovery()
manager.run()
```

Please note that communication with your Bluetooth adapter happens over BlueZ's D-Bus API, hence an event loop needs to be run in order to receive all Bluetooth related events. You can start and stop the event loop via `run()` and `stop()` calls to your `DeviceManager` instance.

### Connecting to a Bluetooth Low Energy device and printing all its information

Once `gatt.DeviceManager` has discovered a Bluetooth device you can use the `gatt.Device` instance that you retrieved from `gatt.DeviceManager.device_discovered()` to connect to it. Alternatively you can create a new instance of `gatt.Device` using the name of your Bluetooth adapter (typically `hci0`) and the device's MAC address.

The following implementation of `gatt.Device` connects to any Bluetooth device and prints all relevant events:

```python
import gatt

manager = gatt.DeviceManager(adapter_name='hci0')

class AnyDevice(gatt.Device):
    def connect_succeeded(self):
        super().connect_succeeded()
        print("[%s] Connected" % (self.mac_address))

    def connect_failed(self, error):
        super().connect_failed(error)
        print("[%s] Connection failed: %s" % (self.mac_address, str(error)))

    def disconnect_succeeded(self):
        super().disconnect_succeeded()
        print("[%s] Disconnected" % (self.mac_address))

    def services_resolved(self):
        super().services_resolved()

        print("[%s] Resolved services" % (self.mac_address))
        for service in self.services:
            print("[%s]  Service [%s]" % (self.mac_address, service.uuid))
            for characteristic in service.characteristics:
                print("[%s]    Characteristic [%s]" % (self.mac_address, characteristic.uuid))


device = AnyDevice(mac_address='AA:BB:CC:DD:EE:FF', manager=manager)
device.connect()

manager.run()
```

As with device discovery, remember to start the Bluetooth event loop with `gatt.DeviceManager.run()`.

### Reading and writing characteristic values

As soon as `gatt.Device.services_resolved()` has been called by the SDK, you can access all GATT services and characteristics. Services are stored in the `services` attribute of `gatt.Device` and each `gatt.Service` instance has a `characteristics` attribute.

To read a characteristic value first get the characteristic and then call `read_value()`. `gatt.Device.characteristic_value_updated()` will be called when the value has been retrieved.

The following example reads the device's firmware version after all services and characteristics have been resolved:

```python
import gatt

manager = gatt.DeviceManager(adapter_name='hci0')

class AnyDevice(gatt.Device):
    def services_resolved(self):
        super().services_resolved()

        device_information_service = next(
            s for s in self.services
            if s.uuid == '0000180a-0000-1000-8000-00805f9b34fb')

        firmware_version_characteristic = next(
            c for c in device_information_service.characteristics
            if c.uuid == '00002a26-0000-1000-8000-00805f9b34fb')

        firmware_version_characteristic.read_value()

    def characteristic_value_updated(self, characteristic, value):
        print("Firmware version:", value.decode("utf-8"))


device = AnyDevice(mac_address='AA:BB:CC:DD:EE:FF', manager=manager)
device.connect()

manager.run()
```

To write a characteristic value simply call `write_value(value)` on the characteristic with `value` being an array of bytes. Then `characteristic_write_value_succeeded()` or `characteristic_write_value_failed(error)` will be called on your `gatt.Device` instance.

### Subscribing for characteristic value changes

To subscribe for characteristic value change notifications call `enable_notifications()` on the characteristic. Then, on your `gatt.Device` instance, `characteristic_enable_notification_succeeded()` or `characteristic_enable_notification_failed()` will be called. Every time the Bluetooth device sends a new value, `characteristic_value_updated()` will be called.

## Support

Please [open an issue](https://github.com/getsenic/gatt-python/issues) for this repository.

## Contributing

Contributions are welcome via pull requests. Please open an issue first in case you want to discus your possible improvements to this SDK.

## License

The GATT SDK for Python is available under the MIT License.
