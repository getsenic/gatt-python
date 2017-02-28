#!/usr/bin/env python3

import sys
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
        return AnyDevice(adapter_name=self.adapter_name, mac_address=mac_address)


class AnyDevice(gatt.Device):
    """
    An implementation of ``gatt.Device`` that connects to any GATT device
    and prints all services and characteristics.
    """

    def __init__(self, adapter_name, mac_address, auto_reconnect=False):
        super().__init__(adapter_name=adapter_name, mac_address=mac_address)
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

    if args.discover:
        device_manager.start_discovery()
    elif args.connect:
        device = AnyDevice(adapter_name=args.adapter, mac_address=args.connect)
        device.connect()
    elif args.auto:
        device = AnyDevice(adapter_name=args.adapter, mac_address=args.auto, auto_reconnect=True)
        device.connect()
    elif args.disconnect:
        device = AnyDevice(adapter_name=args.adapter, mac_address=args.disconnect)
        if not device.is_connected():
            print("Already disconnected")
            return
        device.disconnect()

    print("Terminate with Ctrl+C")
    try:
        device_manager.run()
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
