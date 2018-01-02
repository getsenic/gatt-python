import re

from gi.repository import GObject, Gio, GLib

from . import errors

GObject.threads_init()


class DeviceManager:
    """
    Entry point for managing BLE GATT devices.

    This class is intended to be subclassed to manage a specific set of GATT devices.
    """

    def __init__(self, adapter_name):
        self.listener = None
        self.adapter_name = adapter_name

        self._bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
        object_manager = Gio.DBusObjectManagerClient.new_sync(
            self._bus, Gio.DBusObjectManagerClientFlags.NONE,
            name="org.bluez", object_path="/")
        if object_manager.get_object('/org/bluez/' + adapter_name) is None:
            raise errors.Failed('No object at path "/org/bluez/' + adapter_name + '"')

        self._adapter = Gio.DBusProxy.new_sync(self._bus, Gio.DBusProxyFlags.NONE, None,
                                               'org.bluez',
                                               '/org/bluez/' + adapter_name,
                                               'org.bluez.Adapter1', None)

        self._adapter_properties = Gio.DBusProxy.new_sync(self._bus, Gio.DBusProxyFlags.NONE, None,
                                               'org.bluez',
                                               '/org/bluez/' + adapter_name,
                                               'org.freedesktop.DBus.Properties', None)
        self._object_manager = Gio.DBusProxy.new_sync(self._bus, Gio.DBusProxyFlags.NONE, None,
                                               'org.bluez',
                                               '/',
                                               'org.freedesktop.DBus.ObjectManager', None)
        self._device_path_regex = re.compile('^/org/bluez/' + adapter_name + '/dev((_[A-Z0-9]{2}){6})$')
        self._devices = {}
        self._discovered_devices = {}
        self._interface_added_signal = None
        self._properties_changed_signal = None
        self._main_loop = None

        self.update_devices()

    @property
    def is_adapter_powered(self):
        return self._adapter_properties.Get('(ss)', 'org.bluez.Adapter1', 'Powered') == 1

    @is_adapter_powered.setter
    def is_adapter_powered(self, powered):
        return self._adapter_properties.Set('(ssv)', 'org.bluez.Adapter1', 'Powered', GLib.Variant('b', powered))

    def run(self):
        """
        Starts the main loop that is necessary to receive Bluetooth events from the Bluetooth adapter.

        This call blocks until you call `stop()` to stop the main loop.
        """

        if self._main_loop:
            return

        self._interface_added_signal = self._object_manager.connect(
            'g-signal',
            lambda sender, connection_name, signal, parameters:
                self._interfaces_added(parameters.unpack()[0], parameters.unpack()[1]) if signal == 'InterfacesAdded' else None)

        # TODO: Also listen to 'interfaces removed' events?

        # TODO: Does this signal even make sense given that every device
        #        connects its own PropertiesChanged and the handler only calls
        #        _device_discovered?
        self._properties_changed_signal = self._bus.signal_subscribe(
            None,
            'org.freedesktop.DBus.Properties',
            'PropertiesChanged',
            None,
            'org.bluez.Device1',
            Gio.DBusSignalFlags.NONE,
            lambda conn, sender, path, interface, signal, parameters: self._properties_changed(*parameters.unpack(), path) if signal == "PropertiesChanged" else None)

        def disconnect_signals():
            for device in self._devices.values():
                device.invalidate()
            self._bus.signal_unsubscribe(self._properties_changed_signal)
            self._object_manager.disconnect(self._interface_added_signal)

        self._main_loop = GObject.MainLoop()
        try:
            self._main_loop.run()
            disconnect_signals()
        except:
            disconnect_signals()
            raise

    def stop(self):
        """
        Stops the main loop started with `start()`
        """
        if self._main_loop:
            self._main_loop.quit()
            self._main_loop = None

    def _manage_device(self, device):
        existing_device = self._devices.get(device.mac_address)
        if existing_device is not None:
            existing_device.invalidate()
        self._devices[device.mac_address] = device

    def update_devices(self):
        managed_objects = self._object_manager.GetManagedObjects().items()
        possible_mac_addresses = [self._mac_address(path) for path, _ in managed_objects]
        mac_addresses = [m for m in possible_mac_addresses if m is not None]
        new_mac_addresses = [m for m in mac_addresses if m not in self._devices]
        for mac_address in new_mac_addresses:
            self.make_device(mac_address)
        # TODO: Remove devices from `_devices` that are no longer managed, i.e. deleted

    def devices(self):
        """
        Returns all known Bluetooth devices.
        """
        self.update_devices()
        return self._devices.values()

    def start_discovery(self, service_uuids=[]):
        """Starts a discovery for BLE devices with given service UUIDs.

        :param service_uuids: Filters the search to only return devices with given UUIDs.
        """

        discovery_filter = {'Transport': GLib.Variant('s', 'le')}
        if service_uuids:  # D-Bus doesn't like empty lists, it needs to guess the type
            discovery_filter['UUIDs'] = service_uuids

        try:
            self._adapter.SetDiscoveryFilter('(a{sv})', discovery_filter)
            self._adapter.StartDiscovery()
        except GLib.GError as e:
            if Gio.DBusError.get_remote_error(e) == 'org.bluez.Error.NotReady':
                raise errors.NotReady(
                    "Bluetooth adapter not ready. "
                    "Set `is_adapter_powered` to `True` or run 'echo \"power on\" | sudo bluetoothctl'.")
            if Gio.DBusError.get_remote_error(e) == 'org.bluez.Error.InProgress':
                # Discovery was already started - ignore exception
                pass
            else:
                raise _error_from_dbus_error(e)

    def stop_discovery(self):
        """
        Stops the discovery started with `start_discovery`
        """
        try:
            self._adapter.StopDiscovery()
        except GLib.GError as e:
            if (Gio.DBusError.get_remote_error(e) == 'org.bluez.Error.Failed') and (e.message.endswith('No discovery started')):
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
        device = self._devices.get(mac_address) or self.make_device(mac_address)
        if device is not None:
            self.device_discovered(device)

    def device_discovered(self, device):
        device.advertised()

    def _mac_address(self, device_path):
        match = self._device_path_regex.match(device_path)
        if not match:
            return None
        return match.group(1)[1:].replace('_', ':').lower()

    def make_device(self, mac_address):
        """
        Makes and returns a `Device` instance with specified MAC address.

        Override this method to return a specific subclass instance of `Device`.
        Return `None` if the specified device shall not be supported by this class.
        """
        return Device(mac_address=mac_address, manager=self)

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

    def remove_all_devices(self, skip_alias=None):
        self.update_devices()

        keys_to_be_deleted = []
        for key, device in self._devices.items():
            if skip_alias and device.alias() == skip_alias:
                continue
            mac_address = device.mac_address.replace(':', '_').upper()
            path = '/org/bluez/%s/dev_%s' % (self.adapter_name, mac_address)
            self._adapter.RemoveDevice('(o)', path)
            keys_to_be_deleted.append(key)

        for key in keys_to_be_deleted:
            del self._devices[key]

        self.update_devices()



class Device:
    def __init__(self, mac_address, manager, managed=True):
        """
        Represents a BLE GATT device.

        This class is intended to be sublcassed with a device-specific implementations
        that reflect the device's GATT profile.

        :param mac_address: MAC address of this device
        :manager: `DeviceManager` that shall manage this device
        :managed: If False, the created device will not be managed by the device manager
                  Particularly of interest for sub classes of `DeviceManager` who want
                  to decide on certain device properties if they then create a subclass
                  instance of that `Device` or not.
        """

        self.mac_address = mac_address
        self.manager = manager
        self.services = []

        self._bus = manager._bus
        self._object_manager = manager._object_manager

        # TODO: Device needs to be created if it's not yet known to bluetoothd, see "test-device" in bluez-5.43/test/
        self._device_path = '/org/bluez/%s/dev_%s' % (manager.adapter_name, mac_address.replace(':', '_').upper())
        self._object = Gio.DBusProxy.new_sync(self._bus, Gio.DBusProxyFlags.NONE, None,
                                       'org.bluez',
                                       self._device_path,
                                       'org.bluez.Device1', None)
        self._properties = Gio.DBusProxy.new_sync(self._bus, Gio.DBusProxyFlags.NONE, None,
                                       'org.bluez',
                                       self._device_path,
                                       'org.freedesktop.DBus.Properties', None)
        self._properties_signal = None
        self._connect_retry_attempt = None

        if managed:
            manager._manage_device(self)

    def advertised(self):
        """
        Called when an advertisement package has been received from the device. Requires device discovery to run.
        """
        pass

    def is_registered(self):
        # TODO: Implement, see __init__
        return False

    def register(self):
        # TODO: Implement, see __init__
        return

    def invalidate(self):
        self._disconnect_signals()

    def connect(self):
        """
        Connects to the device. Blocks until the connection was successful.
        """
        self._connect_retry_attempt = 0
        self._connect_signals()
        self._connect()

    def _connect(self):
        self._connect_retry_attempt += 1
        try:
            self._object.Connect()
            if not self.services and self.is_services_resolved():
                self.services_resolved()

        except GLib.GError as e:
            if (Gio.DBusError.get_remote_error(e) == 'org.freedesktop.DBus.Error.UnknownObject'):
                self.connect_failed(errors.Failed("Device does not exist, check adapter name and MAC address."))
            elif ((Gio.DBusError.get_remote_error(e) == 'org.bluez.Error.Failed') and
                  (e.message.endswith("Operation already in progress"))):
                pass
            elif ((self._connect_retry_attempt < 5) and
                  (Gio.DBusError.get_remote_error(e) == 'org.bluez.Error.Failed') and
                  (e.message.endswith("Software caused connection abort"))):
                self._connect()
            elif (Gio.DBusError.get_remote_error(e) == 'org.freedesktop.DBus.Error.NoReply'):
                # TODO: How to handle properly?
                # Reproducable when we repeatedly shut off Nuimo immediately after its flashing Bluetooth icon appears
                self.connect_failed(_error_from_dbus_error(e))
            else:
                self.connect_failed(_error_from_dbus_error(e))

    def _connect_signals(self):
        if self._properties_signal is None:
            self._properties_signal = self._properties.connect(
                'g-signal',
                lambda sender, connection_name, signal, parameters:
                    self.properties_changed(*parameters.unpack()) if signal == 'PropertiesChanged' else None)

        self._connect_service_signals()

    def _connect_service_signals(self):
        for service in self.services:
            service._connect_signals()

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
        self._disconnect_signals()

    def disconnect(self):
        """
        Disconnects from the device, if connected.
        """
        self._object.Disconnect()

    def disconnect_succeeded(self):
        """
        Will be called when the device has disconnected.
        """
        self._disconnect_signals()
        self.services = []

    def _disconnect_signals(self):
        if self._properties_signal is not None:
            self._properties.disconnect(self._properties_signal)
            self._properties_signal = None
        self._disconnect_service_signals()

    def _disconnect_service_signals(self):
        for service in self.services:
            service._disconnect_signals()

    def is_connected(self):
        """
        Returns `True` if the device is connected, otherwise `False`.
        """
        return self._properties.Get('(ss)', 'org.bluez.Device1', 'Connected') == 1

    def is_services_resolved(self):
        """
        Returns `True` is services are discovered, otherwise `False`.
        """
        return self._properties.Get('(ss)', 'org.bluez.Device1', 'ServicesResolved') == 1

    def alias(self):
        """
        Returns the device's alias (name).
        """
        try:
            return self._properties.Get('(ss)', 'org.bluez.Device1', 'Alias')
        except GLib.GError as e:
            if Gio.DBusError.get_remote_error(e) == 'org.freedesktop.DBus.Error.UnknownObject':
                # BlueZ sometimes doesn't provide an alias, we then simply return `None`.
                # Might occur when device was deleted as the following issue points out:
                # https://github.com/blueman-project/blueman/issues/460
                return None
            else:
                raise _error_from_dbus_error(e)

    def properties_changed(self, sender, changed_properties, invalidated_properties):
        """
        Called when a device property has changed or got invalidated.
        """
        if 'Connected' in changed_properties:
            if changed_properties['Connected']:
                self.connect_succeeded()
            else:
                self.disconnect_succeeded()

        if ('ServicesResolved' in changed_properties and changed_properties['ServicesResolved'] == 1 and
                not self.services):
            self.services_resolved()

    def services_resolved(self):
        """
        Called when all device's services and characteristics got resolved.
        """
        self._disconnect_service_signals()

        services_regex = re.compile(self._device_path + '/service[0-9abcdef]{4}$')
        managed_services = [
            service for service in self._object_manager.GetManagedObjects().items()
            if services_regex.match(service[0])]
        self.services = [Service(
            device=self,
            path=service[0],
            uuid=service[1]['org.bluez.GattService1']['UUID']) for service in managed_services]

        self._connect_service_signals()

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
        # TODO: Don'T requore `path` argument, it can be calculated from device's path and uuid
        self.device = device
        self.uuid = uuid
        self._path = path
        self._bus = device._bus
        self._object_manager = device._object_manager
        self.characteristics = []
        self.characteristics_resolved()

    def _connect_signals(self):
        self._connect_characteristic_signals()

    def _connect_characteristic_signals(self):
        for characteristic in self.characteristics:
            characteristic._connect_signals()

    def _disconnect_signals(self):
        self._disconnect_characteristic_signals()

    def _disconnect_characteristic_signals(self):
        for characteristic in self.characteristics:
            characteristic._disconnect_signals()

    def characteristics_resolved(self):
        """
        Called when all service's characteristics got resolved.
        """
        self._disconnect_characteristic_signals()

        characteristics_regex = re.compile(self._path + '/char[0-9abcdef]{4}$')
        managed_characteristics = [
            char for char in self._object_manager.GetManagedObjects().items()
            if characteristics_regex.match(char[0])]
        self.characteristics = [Characteristic(
            service=self,
            path=c[0],
            uuid=c[1]['org.bluez.GattCharacteristic1']['UUID']) for c in managed_characteristics]

        self._connect_characteristic_signals()


class Characteristic:
    """
    Represents a GATT characteristic.
    """

    def __init__(self, service, path, uuid):
        # TODO: Don't require `path` parameter, it can be calculated from service's path and uuid
        self.service = service
        self.uuid = uuid
        self._path = path
        self._bus = service._bus
        self._object_manager = service._object_manager
        self._properties = Gio.DBusProxy.new_sync(self._bus, Gio.DBusProxyFlags.NONE, None,
                                       'org.bluez',
                                       self._path,
                                       'org.freedesktop.DBus.Properties', None)
        self._characteristic = Gio.DBusProxy.new_sync(self._bus, Gio.DBusProxyFlags.NONE, None,
                                       'org.bluez',
                                       self._path,
                                       'org.bluez.GattCharacteristic1', None)
        self._properties_signal = None

    def _connect_signals(self):
        if self._properties_signal is None:
            self._properties_signal = self._properties.connect(
                'g-signal',
                lambda sender, connection_name, signal, parameters:
                    self.properties_changed(*parameters.unpack()) if signal == 'PropertiesChanged' else None)


    def _disconnect_signals(self):
        if self._properties_signal is not None:
            self._properties.disconnect(self._properties_signal)
            self._properties_signal = None

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
            return self._characteristic.ReadValue('(a{sv})',
                {'offset': GLib.Variant("q", offset)})
        except GLib.GError as e:
            error = _error_from_dbus_error(e)
            self.service.device.characteristic_read_value_failed(self, error=error)

    def write_value(self, value, offset=0):
        """
        Attempts to write a value to the characteristic.

        Success or failure will be notified by calls to `write_value_succeeded` or `write_value_failed` respectively.

        :param value: array of bytes to be written
        :param offset: offset from where to start writing the bytes (defaults to 0)
        """
        bytes = value
        try:
            self._characteristic.WriteValue('(aya{sv})',
                bytes,
                {'offset': GLib.Variant("i", offset)},
                result_handler=self._write_value_succeeded,
                error_handler=self._write_value_failed)
        except GLib.GError as e:
            self._write_value_failed(self, gerror=e)

    def _write_value_succeeded(self, proxy, result, user_data):
        """
        Called when the write request has succeeded.
        """
        self.service.device.characteristic_write_value_succeeded(characteristic=self)

    def _write_value_failed(self, proxy, gerror, user_data):
        """
        Called when the write request has failed.
        """
        error = _error_from_dbus_error(gerror)
        self.service.device.characteristic_write_value_failed(characteristic=self, error=error)

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
                self._characteristic.StartNotify(
                    result_handler=self._enable_notifications_succeeded,
                    error_handler=self._enable_notifications_failed,
                    dbus_interface='org.bluez.GattCharacteristic1')
            else:
                self._characteristic.StopNotify(
                    result_handler=self._enable_notifications_succeeded,
                    error_handler=self._enable_notifications_failed,
                    dbus_interface='org.bluez.GattCharacteristic1')
        except GLib.GError as e:
            self._enable_notifications_failed(gerror=e)

    def _enable_notifications_succeeded(self, proxy, result, user_data):
        """
        Called when notification enabling has succeeded.
        """
        self.service.device.characteristic_enable_notifications_succeeded(characteristic=self)

    def _enable_notifications_failed(self, proxy, gerror, user_data):
        """
        Called when notification enabling has failed.
        """
        if ((gerror.code == Gio.DBusError.FAILED) and
            (("Already notifying" in gerror.message) or
             ("No notify session started" in gerror.message))):
            # Ignore cases where notifications where already enabled or already disabled
            return
        error = _error_from_dbus_error(gerror)
        self.service.device.characteristic_enable_notifications_failed(characteristic=self, error=error)


def _error_from_dbus_error(e):
    return {
        'org.bluez.Error.Failed': errors.Failed(e.message),
        'org.bluez.Error.InProgress': errors.InProgress(e.message),
        'org.bluez.Error.InvalidValueLength': errors.InvalidValueLength(e.message),
        'org.bluez.Error.NotAuthorized': errors.NotAuthorized(e.message),
        'org.bluez.Error.NotPermitted': errors.NotPermitted(e.message),
        'org.bluez.Error.NotSupported': errors.NotSupported(e.message),
        'org.freedesktop.DBus.Error.AccessDenied': errors.AccessDenied("Root permissions required")
    }.get(Gio.DBusError.get_remote_error(e), errors.Failed(e.message))
