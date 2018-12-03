import gatt

class AnyDeviceManager(gatt.DeviceManager):
    def device_discovered(self, device):
        print("[%s] Discovered, alias = %s" % (device.mac_address, device.alias()))

manager = AnyDeviceManager(adapter_name='hci0')
manager.start_discovery()
manager.set_timeout(3 * 1000); # Timeout after 3 seconds
manager.run()
