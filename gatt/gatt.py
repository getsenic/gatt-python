import os
import platform

if platform.system() == 'Darwin':
    if os.environ.get('LINUX_WITHOUT_DBUS', '0') == '0':
        from .gatt_linux import *
    else:
        from .gatt_stubs import *
else:
    # TODO: Add support for more platforms
    from .gatt_stubs import *
