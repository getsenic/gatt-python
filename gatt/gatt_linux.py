try:
    import dbus
    import dbus.mainloop.glib
except ImportError:
    import sys
    print("Module 'dbus' not found")
    print("Please run: sudo apt-get install python3-dbus")
    print("See also: https://github.com/getsenic/gatt-python#installing-gatt-sdk-for-python")
    sys.exit(1)

import re

from gi.repository import GObject

from . import errors


dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
dbus.mainloop.glib.threads_init()

_MAIN_LOOP = GObject.MainLoop()


class DeviceManager:
    """
    Entry point for managing BLE GATT devices.

    This class is intended to be subclassed to manage a specific set of GATT devices.
    """

    def __init__(self, adapter_name):
        self.listener = None
        self.adapter_name = adapter_name

        self.bus = dbus.SystemBus()

        try:
            adapter_object = self.bus.get_object('org.bluez', '/org/bluez/' + adapter_name)
        except dbus.exceptions.DBusException as e:
            raise _error_from_dbus_error(e)

        self.adapter = dbus.Interface(adapter_object, 'org.bluez.Adapter1')
        self.device_path_regex = re.compile('^/org/bluez/' + adapter_name + '/dev((_[A-Z0-9]{2}){6})$')

        self._devices = {}
        self._discovered_devices = {}
        self._interface_added_signal = None
        self._properties_changed_signal = None

    def run(self):
        """
        Starts the main loop that is necessary to receive Bluetooth events from the Bluetooth adapter.

        This call blocks until you call `stop()` to stop the main loop.
        """

        object_manager = dbus.Interface(self.bus.get_object("org.bluez", "/"), "org.freedesktop.DBus.ObjectManager")
        possible_mac_addresses = [self._mac_address(path) for path, _ in object_manager.GetManagedObjects().items()]
        mac_addresses = [mac_address for mac_address in possible_mac_addresses if mac_address is not None]
        for mac_address in mac_addresses:
            if self._devices.get(mac_address, None) is not None:
                continue
            device = self.make_device(mac_address)
            if device is not None:
                self._devices[mac_address] = device

        self._interface_added_signal = self.bus.add_signal_receiver(
            self._interfaces_added,
            dbus_interface='org.freedesktop.DBus.ObjectManager',
            signal_name='InterfacesAdded')

        # TODO: Also listen to 'interfaces removed' events?

        self._properties_changed_signal = self.bus.add_signal_receiver(
            self._properties_changed,
            dbus_interface=dbus.PROPERTIES_IFACE,
            signal_name='PropertiesChanged',
            arg0='org.bluez.Device1',
            path_keyword='path')

        _MAIN_LOOP.run()

    def stop(self):
        """
        Stops the main loop started with `start()`
        """
        if self._interface_added_signal is not None:
            self._interface_added_signal.remove()
        if self._properties_changed_signal is not None:
            self._properties_changed_signal.remove()

        _MAIN_LOOP.quit()

    def devices(self):
        """
        Returns all known Bluetooth devices.
        """
        return self._devices()[:]

    def start_discovery(self, service_uuids=[]):
        """Starts a discovery for BLE devices with given service UUIDs.

        :param service_uuids: Filters the search to only return devices with given UUIDs.
        """

        discovery_filter = {'Transport': 'le'}
        if service_uuids:  # D-Bus doesn't like empty lists, it needs to guess the type
            discovery_filter['UUIDs'] = service_uuids

        try:
            self.adapter.SetDiscoveryFilter(discovery_filter)
            self.adapter.StartDiscovery()
        except dbus.exceptions.DBusException as e:
            if e.get_dbus_name() == 'org.bluez.Error.NotReady':
                raise errors.NotReady("Bluetooth adapter not ready. Run 'echo \"power on\" | sudo bluetoothctl'.")
            if e.get_dbus_name() == 'org.bluez.Error.InProgress':
                # Discovery was already started - ignore exception
                pass
            else:
                raise _error_from_dbus_error(e)

    def stop_discovery(self):
        """
        Stops the discovery started with `start_discovery`
        """
        try:
            self.adapter.StopDiscovery()
        except dbus.exceptions.DBusException as e:
            if (e.get_dbus_name() == 'org.bluez.Error.Failed') and (e.get_dbus_message() == 'No discovery started'):
                pass
            else:
                raise _error_from_dbus_error(e)

    def _interfaces_added(self, path, interfaces):
        self._device_discovered(path, interfaces)

    def _properties_changed(self, interface, changed, invalidated, path):
        # TODO: Handle `changed` and `invalidated` properties and update device
        self._device_discovered(path, [interface])

    def _device_discovered(self, path, interfaces):
        if 'org.bluez.Device1' not in interfaces:
            return
        mac_address = self._mac_address(path)
        if not mac_address:
            return
        device = self._devices.get(mac_address, None)
        if device is None:
            device = self.make_device(mac_address)
        if device is None:
            return
        self._devices[mac_address] = device
        self.device_discovered(device)

    def device_discovered(self, device):
        device.advertised()

    def _mac_address(self, device_path):
        match = self.device_path_regex.match(device_path)
        if not match:
            return None
        return match.group(1)[1:].replace('_', ':').lower()

    def make_device(self, mac_address):
        """
        Makes and returns a `Device` instance with specified MAC address.

        Override this method to return a specific subclass instance of `Device`.
        Return `None` if the specified device shall not be supported by this class.
        """
        return Device(adapter_name=self.adapter_name, mac_address=mac_address)

    def add_device(self, mac_address):
        """
        Adds a device with given MAC address without discovery.
        """
        # TODO: Implement
        pass

    def remove_device(self, mac_address):
        """
        Removes a device with the given MAC address
        """
        # TODO: Implement
        pass


class Device:
    def __init__(self, adapter_name, mac_address):
        """
        Represents a BLE GATT device.

        This class is intended to be sublcassed with a device-specific implementations
        that reflect the device's GATT profile.
        """
        self.mac_address = mac_address
        self.bus = dbus.SystemBus()
        self.object_manager = dbus.Interface(
            self.bus.get_object('org.bluez', '/'),
            'org.freedesktop.DBus.ObjectManager')

        # TODO: Get adapter from managed objects? See bluezutils.py
        adapter_object = self.bus.get_object('org.bluez', '/org/bluez/' + adapter_name)
        self.adapter = dbus.Interface(adapter_object, 'org.bluez.Adapter1')

        # TODO: Device needs to be created if it's not yet known to bluetoothd, see "test-device" in bluez-5.43/test/
        self.device_path = '/org/bluez/' + adapter_name + '/dev_' + mac_address.replace(':', '_').upper()
        device_object = self.bus.get_object('org.bluez', self.device_path)
        self.object = dbus.Interface(device_object, 'org.bluez.Device1')
        self.services = []

        self.properties = dbus.Interface(self.object, 'org.freedesktop.DBus.Properties')
        self.properties_signal_match = self.properties.connect_to_signal('PropertiesChanged', self.properties_changed)

    def advertised(self):
        """
        Called when an advertisement package has been received from the device. Requires device discovery to run.
        """

    def invalidate(self):
        """
        Invalidates all properties and services.
        """
        self.properties_signal_match.remove()
        self.invalidate_services()

    def invalidate_services(self):
        """
        Invalidates all services
        """
        for service in self.services:
            service.invalidate()

    def is_registered(self):
        # TODO: Implement, see __init__
        return False

    def register(self):
        # TODO: Implement, see __init__
        return

    def connect(self):
        """
        Connects to the device. Blocks until the connection was successful.
        """
        self._connect_retry_attempt = 0
        self._connect()

    def _connect(self):
        self._connect_retry_attempt += 1
        try:
            self.object.Connect()
            if self.is_services_resolved():
                self.services_resolved()
        except dbus.exceptions.DBusException as e:
            if (e.get_dbus_name() == 'org.freedesktop.DBus.Error.UnknownObject'):
                self.connect_failed(errors.Failed("Device does not exist, check adapter name and MAC address."))
            elif ((e.get_dbus_name() == 'org.bluez.Error.Failed') and
                  (e.get_dbus_message() == "Operation already in progress")):
                pass
            elif ((self._connect_retry_attempt < 5) and
                  (e.get_dbus_name() == 'org.bluez.Error.Failed') and
                  (e.get_dbus_message() == "Software caused connection abort")):
                self._connect()
            elif (e.get_dbus_name() == 'org.freedesktop.DBus.Error.NoReply'):
                # TODO: How to handle properly?
                # Reproducable when we repeatedly shut off Nuimo immediately after its flashing Bluetooth icon appears
                self.connect_failed(_error_from_dbus_error(e))
            else:
                self.connect_failed(_error_from_dbus_error(e))

    def connect_succeeded(self):
        """
        Will be called when `connect()` has finished connecting to the device.
        Will not be called if the device was already connected.
        """
        pass

    def connect_failed(self, error):
        """
        Called when the connection could not be established.
        """
        pass

    def disconnect(self):
        """
        Disconnects from the device, if connected.
        """
        self.object.Disconnect()


    def disconnect_succeeded(self):
        """
        Will be called when the device has disconnected.
        """
        pass

    def is_connected(self):
        """
        Returns `True` if the device is connected, otherwise `False`.
        """
        return self.properties.Get('org.bluez.Device1', 'Connected') == 1

    def is_services_resolved(self):
        """
        Returns `True` is services are discovered, otherwise `False`.
        """
        return self.properties.Get('org.bluez.Device1', 'ServicesResolved') == 1

    def alias(self):
        """
        Returns the device's alias (name).
        """
        return self.properties.Get('org.bluez.Device1', 'Alias')

    def properties_changed(self, sender, changed_properties, invalidated_properties):
        """
        Called when a device property has changed or got invalidated.
        """
        if 'Connected' in changed_properties:
            if changed_properties['Connected']:
                self.connect_succeeded()
            else:
                self.disconnect_succeeded()

        if 'ServicesResolved' in changed_properties and changed_properties['ServicesResolved'] == 1:
            self.services_resolved()

    def services_resolved(self):
        """
        Called when all device's services and characteristics got resolved.
        """
        self.invalidate_services()

        services_regex = re.compile(self.device_path + '/service[0-9abcdef]{4}$')
        managed_services = [
            service for service in self.object_manager.GetManagedObjects().items()
            if services_regex.match(service[0])]
        self.services = [Service(
            device=self,
            path=service[0],
            uuid=service[1]['org.bluez.GattService1']['UUID']) for service in managed_services]

    def characteristic_value_updated(self, characteristic, value):
        """
        Called when a characteristic value has changed.
        """
        # To be implemented by subclass
        pass

    def characteristic_read_value_failed(self, characteristic, error):
        """
        Called when a characteristic value read command failed.
        """
        # To be implemented by subclass
        pass

    def characteristic_write_value_succeeded(self, characteristic):
        """
        Called when a characteristic value write command succeeded.
        """
        # To be implemented by subclass
        pass

    def characteristic_write_value_failed(self, characteristic, error):
        """
        Called when a characteristic value write command failed.
        """
        # To be implemented by subclass
        pass

    def characteristic_enable_notifications_succeeded(self, characteristic):
        """
        Called when a characteristic notifications enable command succeeded.
        """
        # To be implemented by subclass
        pass

    def characteristic_enable_notifications_failed(self, characteristic, error):
        """
        Called when a characteristic notifications enable command failed.
        """
        # To be implemented by subclass
        pass


class Service:
    """
    Represents a GATT service.
    """
    def __init__(self, device, path, uuid):
        self.device = device
        self.path = path
        self.uuid = uuid
        self.bus = device.bus
        self.object_manager = device.object_manager
        self.object = self.bus.get_object('org.bluez', path)
        self.characteristics = []
        self.characteristics_resolved()

    def invalidate(self):
        """
        Invalidates all found characteristics.
        """
        self.invalidate_characteristics()

    def invalidate_characteristics(self):
        """
        Invalidates all found characteristics.
        """
        for characteristic in self.characteristics:
            characteristic.invalidate()

    def characteristics_resolved(self):
        """
        Called when all service's characteristics got resolved.
        """
        self.invalidate_characteristics()

        characteristics_regex = re.compile(self.path + '/char[0-9abcdef]{4}$')
        managed_characteristics = [
            char for char in self.object_manager.GetManagedObjects().items()
            if characteristics_regex.match(char[0])]
        self.characteristics = [Characteristic(
            service=self,
            path=c[0],
            uuid=c[1]['org.bluez.GattCharacteristic1']['UUID']) for c in managed_characteristics]


class Characteristic:
    """
    Represents a GATT characteristic.
    """
    def __init__(self, service, path, uuid):
        self.service = service
        self.path = path
        self.uuid = uuid
        self.bus = service.bus
        self.object_manager = service.object_manager
        self.object = self.bus.get_object('org.bluez', path)
        self.properties = dbus.Interface(self.object, "org.freedesktop.DBus.Properties")
        self.properties_signal = self.properties.connect_to_signal('PropertiesChanged', self.properties_changed)

    def invalidate(self):
        """
        Invalidates the characteristic.
        """
        self.properties_signal.remove()

    def properties_changed(self, properties, changed_properties, invalidated_properties):
        value = changed_properties.get('Value')
        """
        Called when a Characteristic property has changed.
        """
        if value is not None:
            self.service.device.characteristic_value_updated(characteristic=self, value=bytes(value))

    def read_value(self, offset=0):
        """
        Reads the value of this characteristic.

        When successful, `characteristic_value_updated()` of the related device will be called,
        otherwise `characteristic_read_value_failed()` is invoked.
        """
        try:
            return self.object.ReadValue(
                {'offset': dbus.UInt16(offset, variant_level=1)},
                dbus_interface='org.bluez.GattCharacteristic1')
        except dbus.exceptions.DBusException as e:
            error = _error_from_dbus_error(e)
            self.service.device.characteristic_read_value_failed(self, error=error)


    def write_value(self, value, offset=0):
        """
        Attempts to write a value to the characteristic.

        Success or failure will be notified by calls to `write_value_succeeded` or `write_value_failed` respectively.

        :param value: array of bytes to be written
        :param offset: offset from where to start writing the bytes (defaults to 0)
        """
        bytes = [dbus.Byte(b) for b in value]

        try:
            self.object.WriteValue(
                bytes,
                {'offset': dbus.UInt16(offset, variant_level=1)},
                reply_handler=self.write_value_succeeded,
                error_handler=self.write_value_failed,
                dbus_interface='org.bluez.GattCharacteristic1')
        except dbus.exceptions.DBusException as e:
            self.write_value_failed(self, error=e)

    def write_value_succeeded(self):
        """
        Called when the write request has succeeded.
        """
        self.service.device.characteristic_write_value_succeeded(characteristic=self)

    def write_value_failed(self, dbus_error):
        """
        Called when the write request has failed.
        """
        error = _error_from_dbus_error(dbus_error)
        self.service.device.characteristic_write_value_failed(self, error=error)

    def enable_notifications(self, enabled=True):
        """
        Enables or disables value change notifications.

        Success or failure will be notified by calls to `characteristic_enable_notifications_succeeded`
        or `enable_notifications_failed` respectively.

        Each time when the device notifies a new value, `characteristic_value_updated()` of the related
        device will be called.
        """
        try:
            if enabled:
                self.object.StartNotify(
                    reply_handler=self.enable_notifications_succeeded,
                    error_handler=self.enable_notifications_failed,
                    dbus_interface='org.bluez.GattCharacteristic1')
            else:
                self.object.StopNotify(
                    reply_handler=self.enable_notifications_succeeded,
                    error_handler=self.enable_notifications_failed,
                    dbus_interface='org.bluez.GattCharacteristic1')
        except dbus.exceptions.DBusException as e:
            self.enable_notifications_failed(error=e)

    def enable_notifications_succeeded(self):
        """
        Called when notification enabling has succeeded.
        """
        self.service.device.characteristic_enable_notifications_succeeded(characteristic=self)

    def enable_notifications_failed(self, dbus_error):
        """
        Called when notification enabling has failed.
        """
        if ((dbus_error.get_dbus_name() == 'org.bluez.Error.Failed') and
            ((dbus_error.get_dbus_message() == "Already notifying") or
             (dbus_error.get_dbus_message() == "No notify session started"))):
            # Ignore cases where notifications where already enabled or already disabled
            return
        error = _error_from_dbus_error(dbus_error)
        self.service.device.characteristic_enable_notifications_failed(characteristic=self, error=error)


def _error_from_dbus_error(e):
    return {
        'org.bluez.Error.Failed':                  errors.Failed(e.get_dbus_message()),
        'org.bluez.Error.InProgress':              errors.InProgress(e.get_dbus_message()),
        'org.bluez.Error.InvalidValueLength':      errors.InvalidValueLength(e.get_dbus_message()),
        'org.bluez.Error.NotAuthorized':           errors.NotAuthorized(e.get_dbus_message()),
        'org.bluez.Error.NotPermitted':            errors.NotPermitted(e.get_dbus_message()),
        'org.bluez.Error.NotSupported':            errors.NotSupported(e.get_dbus_message()),
        'org.freedesktop.DBus.Error.AccessDenied': errors.AccessDenied("Root permissions required")
    }.get(e.get_dbus_name(), errors.Failed(e.get_dbus_message()))
