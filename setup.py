from setuptools import setup

setup(
    name='gatt',
    packages=['gatt'],
    version='0.1.3',
    description='Bluetooth GATT SDK for Python',
    keywords='gatt',
    url='https://github.com/getsenic/gatt-python',
    download_url='https://github.com/getsenic/gatt-python/archive/0.1.0.tar.gz',
    author='Senic GmbH',
    author_email='developers@senic.com',
    license='MIT',
    py_modules=['gattctl'],
    entry_points={
        'console_scripts': ['gattctl = gattctl:main']
    }
)
