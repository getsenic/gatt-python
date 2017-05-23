#!/usr/bin/env python3

from argparse import ArgumentParser
import gatt

device_manager = None


class AnyDeviceManager(gatt.DeviceManager):
    """
    An implementation of ``gatt.DeviceManager`` that discovers any GATT device
    and prints all discovered devices.
    """

    def device_discovered(self, device):
        print("[%s] Discovered, alias = %s" % (device.mac_address, device.alias()))

    def make_device(self, mac_address):
        return AnyDevice(mac_address=mac_address, manager=self)


class AnyDevice(gatt.Device):
    """
    An implementation of ``gatt.Device`` that connects to any GATT device
    and prints all services and characteristics.
    """

    def __init__(self, mac_address, manager, auto_reconnect=False):
        super().__init__(mac_address=mac_address, manager=manager)
        self.auto_reconnect = auto_reconnect

    def connect(self):
        print("Connecting...")
        super().connect()

    def connect_succeeded(self):
        super().connect_succeeded()
        print("[%s] Connected" % (self.mac_address))

    def connect_failed(self, error):
        super().connect_failed(error)
        print("[%s] Connection failed: %s" % (self.mac_address, str(error)))

    def disconnect_succeeded(self):
        super().disconnect_succeeded()

        print("[%s] Disconnected" % (self.mac_address))
        if self.auto_reconnect:
            self.connect()

    def services_resolved(self):
        super().services_resolved()

        print("[%s] Resolved services" % (self.mac_address))
        for service in self.services:
            print("[%s]  Service [%s]" % (self.mac_address, service.uuid))
            for characteristic in service.characteristics:
                print("[%s]    Characteristic [%s]" % (self.mac_address, characteristic.uuid))


def main():
    arg_parser = ArgumentParser(description="GATT SDK Demo")
    arg_parser.add_argument(
        '--adapter',
        default='hci0',
        help="Name of Bluetooth adapter, defaults to 'hci0'")
    arg_commands_group = arg_parser.add_mutually_exclusive_group(required=True)
    arg_commands_group.add_argument(
        '--power-on',
        action='store_true',
        help="Powers the adapter on")
    arg_commands_group.add_argument(
        '--power-off',
        action='store_true',
        help="Powers the adapter off")
    arg_commands_group.add_argument(
        '--powered',
        action='store_true',
        help="Print the adapter's power state")
    arg_commands_group.add_argument(
        '--discover',
        action='store_true',
        help="Lists all nearby GATT devices")
    arg_commands_group.add_argument(
        '--connect',
        metavar='address',
        type=str,
        help="Connect to a GATT device with a given MAC address")
    arg_commands_group.add_argument(
        '--auto',
        metavar='address',
        type=str,
        help="Connect and automatically reconnect to a GATT device with a given MAC address")
    arg_commands_group.add_argument(
        '--disconnect',
        metavar='address',
        type=str,
        help="Disconnect a GATT device with a given MAC address")
    args = arg_parser.parse_args()

    global device_manager
    device_manager = AnyDeviceManager(adapter_name=args.adapter)

    if args.power_on:
        device_manager.is_adapter_powered = True
        print("Powered on")
        return
    elif args.power_off:
        device_manager.is_adapter_powered = False
        print("Powered off")
        return
    elif args.powered:
        print("Powered: ", device_manager.is_adapter_powered)
        return
    if args.discover:
        device_manager.start_discovery()
    elif args.connect:
        device = AnyDevice(mac_address=args.connect, manager=device_manager)
        device.connect()
    elif args.auto:
        device = AnyDevice(mac_address=args.auto, manager=device_manager, auto_reconnect=True)
        device.connect()
    elif args.disconnect:
        device = AnyDevice(mac_address=args.disconnect, manager=device_manager)
        device.disconnect()
        return

    print("Terminate with Ctrl+C")
    try:
        device_manager.run()
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
