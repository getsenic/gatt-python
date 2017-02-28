import gatt

from argparse import ArgumentParser

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


arg_parser = ArgumentParser(description="GATT Read Firmware Version Demo")
arg_parser.add_argument('mac_address', help="MAC address of device to connect")
args = arg_parser.parse_args()

device = AnyDevice(adapter_name='hci0', mac_address=args.mac_address)
device.connect()

manager = gatt.DeviceManager(adapter_name='hci0')
manager.run()
