import platform

if platform.system() == 'Linux':
    from . import gatt_linux
else:
    # TODO: Add support for more platforms
    class DeviceManager:
        pass


    class Device:
        pass


    class Service:
        pass


    class Characteristic:
        pass
