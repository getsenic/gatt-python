#!/usr/bin/env python3

from argparse import ArgumentParser
from threading import Thread
import keyboard
from termios import tcflush, TCIFLUSH
import gatt
import time
import sys

device_manager = None


class AnyDeviceManager(gatt.DeviceManager):
    """
    An implementation of ``gatt.DeviceManager`` that discovers any GATT device
    and prints all discovered devices.
    """
    def __init__(self, adapter_name):
        super().__init__(adapter_name)
        self.nb_device_connected = 0
        self.discover_filter = 'True'

    def device_discovered(self, device):
        if self.discover_filter == 'True':
            print("[%s] Discovered, alias = %s" % (device.mac_address, device.alias()))
        elif self.discover_filter in device.alias() or self.discover_filter in device.mac_address:
            print("[%s] Discovered, alias = %s" % (device.mac_address, device.alias()))

    def make_device(self, mac_address):
        return AnyDevice(mac_address=mac_address, manager=self)

    def run(self):
        print("Running Manager")
        super().run()

    def quit(self):
        print("Stopping Manager")
        super().stop()


class AnyDevice(gatt.Device):
    """
    An implementation of ``gatt.Device`` that connects to any GATT device
    and prints all services and characteristics.
    """

    def __init__(self, mac_address, manager, auto_reconnect=False):
        super().__init__(mac_address=mac_address, manager=manager)
        self.auto_reconnect = auto_reconnect
        self.message = ''
        self.transmition = ""
        self.reception = ""

    def connect(self):
        print("Connecting...")
        super().connect()

    def connect_succeeded(self):
        super().connect_succeeded()
        device_manager.nb_device_connected += 1
        print("[%s] Connected" % (self.mac_address))

    def connect_failed(self, error):
        super().connect_failed(error)
        print("[%s] Connection failed: %s" % (self.mac_address, str(error)))

    def disconnect_succeeded(self):
        if device_manager.nb_device_connected:
            device_manager.nb_device_connected -= 1
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
                if characteristic.uuid == '6e400003-b5a3-f393-e0a9-e50e24dcca9e':
                    characteristic.enable_notifications()

                print("[%s]    Characteristic [%s]" % (self.mac_address, characteristic.uuid))
        print("[%s] Resolved services" % (self.mac_address))

        device_service = next(
            s for s in self.services
            if s.uuid == '6e400001-b5a3-f393-e0a9-e50e24dcca9e')

        self.reception = next(
            c for c in device_service.characteristics
            if c.uuid == '6e400003-b5a3-f393-e0a9-e50e24dcca9e')

        self.transmition = next(
            c for c in device_service.characteristics
            if c.uuid == '6e400002-b5a3-f393-e0a9-e50e24dcca9e')

        if self.message:
            bar = bytearray(self.message.encode())
            self.transmition.write_value(bar)

        time.sleep(2)
        self.reception.read_value()

    def characteristic_value_updated(self, characteristic, value):
        print("RX:", (value.decode("utf-8")).replace('\n', ''))

    def characteristic_read_value_failed(self, characteristic, error):
        print("RX fail : ", error)

    def characteristic_enable_notifications_succeeded(self, characteristic):
        print("enable notification succeeded for characteristic ", characteristic.uuid)

    def characteristic_enable_notifications_failed(self, characteristic, error):
        print("enable notification succeeded for characteristic ", characteristic.uuid, ", error, ", error)

    def characteristic_write_value_succeeded(self, characteristic):
        print("write value succeeded for characteristic ", characteristic.uuid)

    def characteristic_write_value_failed(self, characteristic, error):
        print("write value fail for characteristic ", characteristic.uuid, ", error, ", error)


def main():
    arg_parser = ArgumentParser(description="GATT SDK Demo")
    arg_parser.add_argument(
        '--adapter',
        default='hci0',
        help="Name of Bluetooth adapter, defaults to 'hci0'")
    arg_parser.add_argument(
        '--message',
        metavar='string',
        type=str,
        help="String send by ble, usable with --connect only. All 'n' of the message will be remplace by '\ n' ")
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
        '--discover-filter',
        metavar='filter',
        type=str,
        help="Lists all nearby GATT devices containing filter in their MAC address or alias")
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
    if args.discover_filter:
        print("discover filter : ", args.discover_filter)
        device_manager.discover_filter = args.discover_filter
        device_manager.start_discovery()
    elif args.connect:
        device = AnyDevice(mac_address=args.connect, manager=device_manager)
        if args.message:
            device.message = (args.message.replace('%n','\n'))
        device.connect()
    elif args.auto:
        device = AnyDevice(mac_address=args.auto, manager=device_manager, auto_reconnect=True)
        device.connect()
    elif args.disconnect:
        device = AnyDevice(mac_address=args.disconnect, manager=device_manager)
        device.disconnect()
        return

    thread = Thread(target=device_manager.run)
    thread.start()

    print("Terminate with Ctrl+C")
    print("Started Thread.")

    try:
        while True:
            if device_manager.nb_device_connected:
                # If ESCAPE key is pressed you can start to write the message, ENTER to send it to the device
                if keyboard.is_pressed(chr(27)):
                    tcflush(sys.stdin, TCIFLUSH)
                    message = bytearray(input(">> ").replace('%n','\n').encode())
                    device.transmition.write_value(message)

            pass
    except KeyboardInterrupt:
        print('KeyboardInterrupt!')
        if device_manager.nb_device_connected:
            device.disconnect()
        device_manager.quit()
    thread.join()

if __name__ == '__main__':
    main()
