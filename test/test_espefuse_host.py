#!/usr/bin/env python
#
# HOST_TEST for espefuse.py
# [support esp32, esp32s2, esp32s3beta2, esp32s3, esp32c3, esp32h2beta1, esp32c2]
#
# How to use it:
#
# 1. Run as HOST_TEST (without a physical connection to a chip):
#    - `python test_espefuse_host.py esp32`
#    - `python test_espefuse_host.py esp32s2`
#
# 2. Run as TEST on FPGA (connection to FPGA with a flashed image):
#    required two COM ports
#    - `python test_espefuse_host.py esp32   /dev/ttyUSB0 /dev/ttyUSB1`
#    - `python test_espefuse_host.py esp32s2 /dev/ttyUSB0 /dev/ttyUSB1`
#
# where  - ttyUSB0 - a port for espefuse.py operation
#        - ttyUSB1 - a port to clear efuses (connect RTS or DTR ->- J14 pin 39)
#
# Note: For FPGA with ESP32 image, you need to set an env variable ESPTOOL_ENV_FPGA to 1
#       to slow down the connection sequence
#       because of a long delay (~6 seconds) after resetting the FPGA.
#       This is not necessary when using other images than ESP32

import os
import subprocess
import sys
import tempfile
import time
import unittest

from bitstring import BitString

import serial

TEST_DIR = os.path.abspath(os.path.dirname(__file__))
ESPEFUSE_PY = os.path.abspath(os.path.join(TEST_DIR, "..", "espefuse/__init__.py"))
ESPEFUSE_DIR = os.path.abspath(os.path.join(TEST_DIR, ".."))
os.chdir(TEST_DIR)
sys.path.insert(0, os.path.join(TEST_DIR, ".."))

support_list_chips = [
    "esp32",
    "esp32s2",
    "esp32s3beta2",
    "esp32s3",
    "esp32c3",
    "esp32h2beta1",
    "esp32c2",
]

try:
    chip_target = sys.argv[1]
except IndexError:
    chip_target = "esp32"

global reset_port
reset_port = None
global espefuse_port
espefuse_port = None


class EfuseTestCase(unittest.TestCase):
    def setUp(self):
        if reset_port is None:
            self.efuse_file = tempfile.NamedTemporaryFile()
            self.base_cmd = (
                "python {} --chip {} --virt --path-efuse-file {} -d ".format(
                    ESPEFUSE_PY, chip_target, self.efuse_file.name
                )
            )
        else:
            self.base_cmd = "python {} --chip {} -p {} -d ".format(
                ESPEFUSE_PY, chip_target, espefuse_port
            )
            self.reset_efuses()

    def tearDown(self):
        if reset_port is None:
            self.efuse_file.close()

    def reset_efuses(self):
        # reset and zero efuses
        reset_port.dtr = False
        reset_port.rts = False
        time.sleep(0.05)
        reset_port.dtr = True
        reset_port.rts = True
        time.sleep(0.05)
        reset_port.dtr = False
        reset_port.rts = False

    def get_esptool(self):
        if espefuse_port is not None:
            import esptool

            esp = esptool.cmds.detect_chip(port=espefuse_port)
            del esptool
        else:
            import espefuse

            efuse = espefuse.SUPPORTED_CHIPS[chip_target].efuse_lib
            esp = efuse.EmulateEfuseController(self.efuse_file.name)
            del espefuse
            del efuse
        return esp

    def _set_34_coding_scheme(self):
        self.espefuse_py("burn_efuse CODING_SCHEME 1")

    def check_data_block_in_log(
        self, log, file_path, repeat=1, reverse_order=False, offset=0
    ):
        with open(file_path, "rb") as f:
            data = BitString("0x00") * offset + BitString(f)
            blk = data.readlist("%d*uint:8" % (data.len // 8))
            blk = blk[::-1] if reverse_order else blk
            hex_blk = " ".join("{:02x}".format(num) for num in blk)
            self.assertEqual(repeat, log.count(hex_blk))

    def espefuse_not_virt_py(self, cmd, check_msg=None, ret_code=0):
        full_cmd = " ".join(("python {}".format(ESPEFUSE_PY), cmd))
        return self._run_command(full_cmd, check_msg, ret_code)

    def espefuse_py(self, cmd, do_not_confirm=True, check_msg=None, ret_code=0):
        full_cmd = " ".join(
            [self.base_cmd, "--do-not-confirm" if do_not_confirm else "", cmd]
        )
        output = self._run_command(full_cmd, check_msg, ret_code)
        self._run_command(
            " ".join([self.base_cmd, "check_error"]), "No errors detected", 0
        )
        return output

    def _run_command(self, cmd, check_msg, ret_code):
        try:
            p = subprocess.Popen(
                cmd.split(),
                shell=False,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                universal_newlines=True,
            )
            output, _ = p.communicate()
            returncode = p.returncode
            if check_msg:
                self.assertIn(check_msg, output)
            if returncode:
                print(output)
            self.assertEqual(ret_code, returncode)
            return output
        except subprocess.CalledProcessError as error:
            print(error)
            raise


class TestReadCommands(EfuseTestCase):
    def test_help(self):
        self.espefuse_not_virt_py("--help", check_msg="usage: __init__.py [-h]")
        self.espefuse_not_virt_py("--chip %s --help" % (chip_target))

    def test_help2(self):
        self.espefuse_not_virt_py("", check_msg="usage: __init__.py [-h]", ret_code=1)

    def test_dump(self):
        self.espefuse_py("dump -h")
        self.espefuse_py("dump")

    def test_summary(self):
        self.espefuse_py("summary -h")
        self.espefuse_py("summary")

    def test_summary_json(self):
        self.espefuse_py("summary --format json")

    def test_get_custom_mac(self):
        self.espefuse_py("get_custom_mac -h")
        if chip_target == "esp32":
            right_msg = "Custom MAC Address is not set in the device."
        elif chip_target == "esp32h2beta1":
            right_msg = "Custom MAC Address: 00:00:00:00:00:00:00:00 (OK)"
        else:
            right_msg = "Custom MAC Address: 00:00:00:00:00:00 (OK)"
        self.espefuse_py("get_custom_mac", check_msg=right_msg)

    def test_adc_info(self):
        self.espefuse_py("adc_info -h")
        self.espefuse_py("adc_info")

    def test_check_error(self):
        self.espefuse_py("check_error -h")
        self.espefuse_py("check_error")
        self.espefuse_py("check_error --recovery")


class TestReadProtectionCommands(EfuseTestCase):
    def test_read_protect_efuse(self):
        self.espefuse_py("read_protect_efuse -h")
        if chip_target == "esp32":
            cmd = "read_protect_efuse \
                   CODING_SCHEME \
                   MAC_VERSION \
                   BLOCK1 \
                   BLOCK2 \
                   BLOCK3"
            count_protects = 5
        elif chip_target == "esp32c2":
            cmd = "read_protect_efuse \
                   BLOCK_KEY0_LOW_128"
            count_protects = 1
        else:
            self.espefuse_py(
                "burn_efuse \
                KEY_PURPOSE_0 HMAC_UP \
                KEY_PURPOSE_1 XTS_AES_128_KEY \
                KEY_PURPOSE_2 XTS_AES_128_KEY \
                KEY_PURPOSE_3 HMAC_DOWN_ALL \
                KEY_PURPOSE_4 HMAC_DOWN_JTAG \
                KEY_PURPOSE_5 HMAC_DOWN_DIGITAL_SIGNATURE"
            )
            cmd = "read_protect_efuse \
                   BLOCK_KEY0 \
                   BLOCK_KEY1 \
                   BLOCK_KEY2 \
                   BLOCK_KEY3 \
                   BLOCK_KEY4 \
                   BLOCK_KEY5"
            count_protects = 6
        self.espefuse_py(cmd)
        output = self.espefuse_py(cmd)
        self.assertEqual(count_protects, output.count("is already read protected"))

    def test_read_protect_efuse2(self):
        self.espefuse_py("write_protect_efuse RD_DIS")
        if chip_target == "esp32":
            efuse_name = "CODING_SCHEME"
        elif chip_target == "esp32c2":
            efuse_name = "BLOCK_KEY0_HI_128"
        else:
            efuse_name = "BLOCK_SYS_DATA2"
        self.espefuse_py(
            "read_protect_efuse {}".format(efuse_name),
            check_msg="A fatal error occurred: This efuse cannot be read-disabled "
            "due the to RD_DIS field is already write-disabled",
            ret_code=2,
        )

    @unittest.skipUnless(chip_target == "esp32", "when the purpose of BLOCK2 is set")
    def test_read_protect_efuse3(self):
        self.espefuse_py("burn_efuse ABS_DONE_1 1")
        self.espefuse_py("burn_key BLOCK2 images/efuse/256bit")
        self.espefuse_py(
            "read_protect_efuse BLOCK2",
            check_msg="Secure Boot V2 is on (ABS_DONE_1 = True), "
            "BLOCK2 must be readable, stop this operation!",
            ret_code=2,
        )

    def test_read_protect_efuse4(self):
        if chip_target == "esp32":
            self.espefuse_py("burn_key BLOCK2 images/efuse/256bit")
            msg = "must be readable, please stop this operation!"
            self.espefuse_py("read_protect_efuse BLOCK2", check_msg=msg)
        elif chip_target == "esp32c2":
            self.espefuse_py(
                "burn_key BLOCK_KEY0 images/efuse/128bit_key SECURE_BOOT_DIGEST"
            )
            self.espefuse_py(
                "read_protect_efuse BLOCK_KEY0",
                check_msg="A fatal error occurred: "
                "BLOCK_KEY0 must be readable, stop this operation!",
                ret_code=2,
            )
        else:
            self.espefuse_py(
                "burn_key BLOCK_KEY0 images/efuse/256bit USER \
                BLOCK_KEY1 images/efuse/256bit RESERVED \
                BLOCK_KEY2 images/efuse/256bit SECURE_BOOT_DIGEST0 \
                BLOCK_KEY3 images/efuse/256bit SECURE_BOOT_DIGEST1 \
                BLOCK_KEY4 images/efuse/256bit SECURE_BOOT_DIGEST2 \
                BLOCK_KEY5 images/efuse/256bit HMAC_UP"
            )
            self.espefuse_py(
                "read_protect_efuse BLOCK_KEY0",
                check_msg="A fatal error occurred: "
                "BLOCK_KEY0 must be readable, stop this operation!",
                ret_code=2,
            )
            self.espefuse_py(
                "read_protect_efuse BLOCK_KEY1",
                check_msg="A fatal error occurred: "
                "BLOCK_KEY1 must be readable, stop this operation!",
                ret_code=2,
            )
            self.espefuse_py(
                "read_protect_efuse BLOCK_KEY2",
                check_msg="A fatal error occurred: "
                "BLOCK_KEY2 must be readable, stop this operation!",
                ret_code=2,
            )
            self.espefuse_py(
                "read_protect_efuse BLOCK_KEY3",
                check_msg="A fatal error occurred: "
                "BLOCK_KEY3 must be readable, stop this operation!",
                ret_code=2,
            )
            self.espefuse_py(
                "read_protect_efuse BLOCK_KEY4",
                check_msg="A fatal error occurred: "
                "BLOCK_KEY4 must be readable, stop this operation!",
                ret_code=2,
            )
            self.espefuse_py("read_protect_efuse BLOCK_KEY5")

    @unittest.skipUnless(
        chip_target == "esp32",
        "system parameters efuse read-protection is supported only by esp32, "
        "other chips protect whole blocks",
    )
    def test_burn_and_read_protect_efuse(self):
        self.espefuse_py(
            "burn_efuse FLASH_CRYPT_CONFIG 15 RD_DIS 8",
            check_msg="Efuse FLASH_CRYPT_CONFIG is read-protected. "
            "Read back the burn value is not possible.",
        )


class TestWriteProtectionCommands(EfuseTestCase):
    def test_write_protect_efuse(self):
        self.espefuse_py("write_protect_efuse -h")
        if chip_target == "esp32":
            efuse_lists = """WR_DIS RD_DIS CODING_SCHEME CHIP_VERSION CHIP_PACKAGE
                           XPD_SDIO_FORCE XPD_SDIO_REG XPD_SDIO_TIEH SPI_PAD_CONFIG_CLK
                           FLASH_CRYPT_CNT UART_DOWNLOAD_DIS FLASH_CRYPT_CONFIG
                           ADC_VREF BLOCK1 BLOCK2 BLOCK3"""
            efuse_lists2 = "WR_DIS RD_DIS"
        elif chip_target == "esp32c2":
            efuse_lists = """RD_DIS DIS_DOWNLOAD_ICACHE
                           XTS_KEY_LENGTH_256 UART_PRINT_CONTROL"""
            efuse_lists2 = "RD_DIS DIS_DOWNLOAD_ICACHE"
        else:
            efuse_lists = """RD_DIS DIS_ICACHE DIS_DOWNLOAD_ICACHE DIS_FORCE_DOWNLOAD
                           DIS_CAN SOFT_DIS_JTAG DIS_DOWNLOAD_MANUAL_ENCRYPT
                           USB_EXCHG_PINS WDT_DELAY_SEL SPI_BOOT_CRYPT_CNT
                           SECURE_BOOT_KEY_REVOKE0 SECURE_BOOT_KEY_REVOKE1
                           SECURE_BOOT_KEY_REVOKE2 KEY_PURPOSE_0 KEY_PURPOSE_1
                           KEY_PURPOSE_2 KEY_PURPOSE_3 KEY_PURPOSE_4 KEY_PURPOSE_5
                           SECURE_BOOT_EN SECURE_BOOT_AGGRESSIVE_REVOKE FLASH_TPUW
                           DIS_DOWNLOAD_MODE DIS_DIRECT_BOOT
                           DIS_USB_SERIAL_JTAG_ROM_PRINT
                           DIS_USB_SERIAL_JTAG_DOWNLOAD_MODE ENABLE_SECURITY_DOWNLOAD
                           UART_PRINT_CONTROL MAC SPI_PAD_CONFIG_CLK SPI_PAD_CONFIG_Q
                           SPI_PAD_CONFIG_D SPI_PAD_CONFIG_CS SPI_PAD_CONFIG_HD
                           SPI_PAD_CONFIG_WP SPI_PAD_CONFIG_DQS SPI_PAD_CONFIG_D4
                           SPI_PAD_CONFIG_D5 SPI_PAD_CONFIG_D6 SPI_PAD_CONFIG_D7
                           WAFER_VERSION PKG_VERSION BLOCK1_VERSION OPTIONAL_UNIQUE_ID
                           BLOCK2_VERSION BLOCK_USR_DATA BLOCK_KEY0 BLOCK_KEY1
                           BLOCK_KEY2 BLOCK_KEY3 BLOCK_KEY4 BLOCK_KEY5"""
            efuse_lists2 = "RD_DIS DIS_ICACHE"
        if chip_target == "esp32s2":
            replace_rule = {
                # New bit definition after esp32c3    Old defintion in esp32s2
                "DIS_USB_SERIAL_JTAG_DOWNLOAD_MODE": "DIS_USB_DOWNLOAD_MODE",
                "DIS_DIRECT_BOOT": "DIS_LEGACY_SPI_BOOT",
                "DIS_USB_SERIAL_JTAG_ROM_PRINT": "UART_PRINT_CHANNEL",
            }
            for old_name in replace_rule:
                efuse_lists = efuse_lists.replace(old_name, replace_rule[old_name])
        self.espefuse_py("write_protect_efuse {}".format(efuse_lists))
        output = self.espefuse_py("write_protect_efuse {}".format(efuse_lists2))
        self.assertEqual(2, output.count("is already write protected"))

    def test_write_protect_efuse2(self):
        if chip_target == "esp32":
            self.espefuse_py("write_protect_efuse WR_DIS")
            self.espefuse_py(
                "write_protect_efuse CODING_SCHEME",
                check_msg="A fatal error occurred: This efuse cannot be write-disabled "
                "due to the WR_DIS field is already write-disabled",
                ret_code=2,
            )


class TestBurnCustomMacCommands(EfuseTestCase):
    def test_burn_custom_mac(self):
        self.espefuse_py("burn_custom_mac -h")
        cmd = "burn_custom_mac AA:CD:EF:11:22:33"
        if chip_target == "esp32":
            self.espefuse_py(
                cmd,
                check_msg="Custom MAC Address version 1: "
                "aa:cd:ef:11:22:33 (CRC 0x63 OK)",
            )
        else:
            mac_custom = (
                "aa:cd:ef:11:22:33:00:00"
                if chip_target == "esp32h2beta1"
                else "aa:cd:ef:11:22:33"
            )
            self.espefuse_py(cmd, check_msg="Custom MAC Address: %s (OK)" % mac_custom)

    def test_burn_custom_mac2(self):
        self.espefuse_py(
            "burn_custom_mac AA:CD:EF:11:22:33:44",
            check_msg="A fatal error occurred: MAC Address needs to be a 6-byte "
            "hexadecimal format separated by colons (:)!",
            ret_code=2,
        )

    def test_burn_custom_mac3(self):
        self.espefuse_py(
            "burn_custom_mac AB:CD:EF:11:22:33",
            check_msg="A fatal error occurred: Custom MAC must be a unicast MAC!",
            ret_code=2,
        )

    @unittest.skipUnless(chip_target == "esp32", "3/4 coding scheme is only in esp32")
    def test_burn_custom_mac_with_34_coding_scheme(self):
        self._set_34_coding_scheme()
        self.espefuse_py("burn_custom_mac -h")
        self.espefuse_py(
            "burn_custom_mac AA:CD:EF:01:02:03",
            check_msg="Custom MAC Address version 1: aa:cd:ef:01:02:03 (CRC 0x56 OK)",
        )
        self.espefuse_py(
            "get_custom_mac",
            check_msg="Custom MAC Address version 1: aa:cd:ef:01:02:03 (CRC 0x56 OK)",
        )

        self.espefuse_py(
            "burn_custom_mac FE:22:33:44:55:66",
            check_msg="New value contains some bits that cannot be cleared "
            "(value will be 0x675745ffeffe)",
            ret_code=2,
        )


@unittest.skipIf(
    chip_target == "esp32c2", "TODO: add support set_flash_voltage for ESP32-C2"
)
@unittest.skipIf(
    chip_target == "esp32h2beta1", "TODO: add support set_flash_voltage for ESP32-H2"
)
@unittest.skipIf(
    chip_target == "esp32c3", "TODO: add support set_flash_voltage for ESP32-C3"
)
class TestSetFlashVoltageCommands(EfuseTestCase):
    def test_set_flash_voltage_1_8v(self):
        self.espefuse_py("set_flash_voltage -h")
        vdd = "VDD_SDIO" if chip_target == "esp32" else "VDD_SPI"
        self.espefuse_py(
            "set_flash_voltage 1.8V",
            check_msg="Set internal flash voltage regulator (%s) to 1.8V." % vdd,
        )
        if chip_target == "esp32":
            error_msg = "A fatal error occurred: "
            "Can't set flash regulator to OFF as XPD_SDIO_REG efuse is already burned"
        else:
            error_msg = "A fatal error occurred: "
            "Can't set flash regulator to OFF as VDD_SPI_XPD efuse is already burned"
        self.espefuse_py(
            "set_flash_voltage 3.3V",
            check_msg="Enable internal flash voltage regulator (%s) to 3.3V." % vdd,
        )
        self.espefuse_py("set_flash_voltage OFF", check_msg=error_msg, ret_code=2)

    def test_set_flash_voltage_3_3v(self):
        vdd = "VDD_SDIO" if chip_target == "esp32" else "VDD_SPI"
        self.espefuse_py(
            "set_flash_voltage 3.3V",
            check_msg="Enable internal flash voltage regulator (%s) to 3.3V." % vdd,
        )
        if chip_target == "esp32":
            error_msg = "A fatal error occurred: "
            "Can't set regulator to 1.8V is XPD_SDIO_TIEH efuse is already burned"
        else:
            error_msg = "A fatal error occurred: "
            "Can't set regulator to 1.8V is VDD_SPI_TIEH efuse is already burned"
        self.espefuse_py("set_flash_voltage 1.8V", check_msg=error_msg, ret_code=2)

        if chip_target == "esp32":
            error_msg = "A fatal error occurred: "
            "Can't set flash regulator to OFF as XPD_SDIO_REG efuse is already burned"
        else:
            error_msg = "A fatal error occurred: "
            "Can't set flash regulator to OFF as VDD_SPI_XPD efuse is already burned"
        self.espefuse_py("set_flash_voltage OFF", check_msg=error_msg, ret_code=2)

    def test_set_flash_voltage_off(self):
        vdd = "VDD_SDIO" if chip_target == "esp32" else "VDD_SPI"
        self.espefuse_py(
            "set_flash_voltage OFF",
            check_msg="Disable internal flash voltage regulator (%s)" % vdd,
        )
        self.espefuse_py(
            "set_flash_voltage 3.3V",
            check_msg="Enable internal flash voltage regulator (%s) to 3.3V." % vdd,
        )

    def test_set_flash_voltage_off2(self):
        vdd = "VDD_SDIO" if chip_target == "esp32" else "VDD_SPI"
        self.espefuse_py(
            "set_flash_voltage OFF",
            check_msg="Disable internal flash voltage regulator (%s)" % vdd,
        )
        self.espefuse_py(
            "set_flash_voltage 1.8V",
            check_msg="Set internal flash voltage regulator (%s) to 1.8V." % vdd,
        )


class TestBurnEfuseCommands(EfuseTestCase):
    @unittest.skipUnless(
        chip_target == "esp32",
        "IO pins 30 & 31 cannot be set for SPI flash only on esp32",
    )
    def test_set_spi_flash_pin_efuses(self):
        self.espefuse_py(
            "burn_efuse SPI_PAD_CONFIG_HD 30",
            check_msg="A fatal error occurred: "
            "IO pins 30 & 31 cannot be set for SPI flash. 0-29, 32 & 33 only.",
            ret_code=2,
        )
        self.espefuse_py(
            "burn_efuse SPI_PAD_CONFIG_Q 0x23",
            check_msg="A fatal error occurred: "
            "IO pin 35 cannot be set for SPI flash. 0-29, 32 & 33 only.",
            ret_code=2,
        )
        output = self.espefuse_py("burn_efuse SPI_PAD_CONFIG_CS0 33")
        self.assertIn(
            "(Override SD_CMD pad (GPIO11/SPICS0)) 0b00000 -> 0b11111", output
        )
        self.assertIn("BURN BLOCK0  - OK (write block == read block)", output)

    def test_burn_mac_custom_efuse(self):
        crc_msg = "(OK)"
        self.espefuse_py("burn_efuse -h")
        if chip_target == "esp32":
            self.espefuse_py(
                "burn_efuse MAC AA:CD:EF:01:02:03",
                check_msg="Writing Factory MAC address is not supported",
                ret_code=2,
            )
            self.espefuse_py("burn_efuse MAC_VERSION 1")
            crc_msg = "(CRC 0x56 OK)"
        if chip_target == "esp32c2":
            self.espefuse_py("burn_efuse CUSTOM_MAC_USED 1")
        self.espefuse_py("burn_efuse -h")
        self.espefuse_py(
            "burn_efuse CUSTOM_MAC AB:CD:EF:01:02:03",
            check_msg="A fatal error occurred: Custom MAC must be a unicast MAC!",
            ret_code=2,
        )
        self.espefuse_py("burn_efuse CUSTOM_MAC AA:CD:EF:01:02:03")
        if chip_target in ["esp32h2", "esp32h2beta1"]:
            self.espefuse_py(
                "get_custom_mac", check_msg="aa:cd:ef:01:02:03:00:00 {}".format(crc_msg)
            )
        else:
            self.espefuse_py(
                "get_custom_mac", check_msg="aa:cd:ef:01:02:03 {}".format(crc_msg)
            )

    def test_burn_efuse(self):
        self.espefuse_py("burn_efuse -h")
        if chip_target == "esp32":
            self.espefuse_py(
                "burn_efuse \
                CHIP_VER_REV2 1 \
                DISABLE_DL_ENCRYPT 1 \
                CONSOLE_DEBUG_DISABLE 1"
            )
            blk1 = "BLOCK1"
            blk2 = "BLOCK2"
        elif chip_target == "esp32c2":
            self.espefuse_py(
                "burn_efuse \
                XTS_KEY_LENGTH_256 1 \
                UART_PRINT_CONTROL 1 \
                FORCE_SEND_RESUME 1"
            )
            blk1 = "BLOCK_KEY0"
            blk2 = None
        else:
            self.espefuse_py(
                "burn_efuse \
                SECURE_BOOT_EN 1 \
                UART_PRINT_CONTROL 1"
            )
            self.espefuse_py(
                "burn_efuse \
                OPTIONAL_UNIQUE_ID 0x2328ad5ac9145f698f843a26d6eae168",
                check_msg="-> 0x2328ad5ac9145f698f843a26d6eae168",
            )
            output = self.espefuse_py("summary -d")
            self.assertIn(
                "read_regs: d6eae168 8f843a26 c9145f69 2328ad5a "
                "00000000 00000000 00000000 00000000",
                output,
            )
            self.assertIn(
                "= 68 e1 ea d6 26 3a 84 8f 69 5f 14 c9 5a ad 28 23 R/W", output
            )
            self.espefuse_py(
                "burn_efuse \
                              BLOCK2_VERSION  1",
                check_msg="Burn into BLOCK_SYS_DATA is forbidden "
                "(RS coding scheme does not allow this).",
                ret_code=2,
            )
            blk1 = "BLOCK_KEY1"
            blk2 = "BLOCK_KEY2"
        output = self.espefuse_py(
            "burn_efuse {}".format(blk1)
            + " 0x00010203040506070809111111111111111111111111111111110000112233FF"
        )
        self.assertIn(
            "-> 0x00010203040506070809111111111111111111111111111111110000112233ff",
            output,
        )
        output = self.espefuse_py("summary -d")
        self.assertIn(
            "read_regs: "
            "112233ff 11110000 11111111 11111111 11111111 08091111 04050607 00010203",
            output,
        )
        self.assertIn(
            "= ff 33 22 11 00 00 11 11 11 11 11 11 11 11 11 11 11 11 11 11 11 11 "
            "09 08 07 06 05 04 03 02 01 00 R/W",
            output,
        )

        if blk2 is not None:
            output = self.espefuse_py(
                "burn_efuse {}".format(blk2)
                + " 00010203040506070809111111111111111111111111111111110000112233FF"
            )
            self.assertIn(
                "-> 0xff33221100001111111111111111111111111111111109080706050403020100",
                output,
            )
            output = self.espefuse_py("summary -d")
            self.assertIn(
                "read_regs: 03020100 07060504 11110908 "
                "11111111 11111111 11111111 00001111 ff332211",
                output,
            )
            self.assertIn(
                "= 00 01 02 03 04 05 06 07 08 09 "
                "11 11 11 11 11 11 11 11 11 11 11 11 11 11 11 11 00 00 11 22 33 ff R/W",
                output,
            )

    @unittest.skipUnless(chip_target == "esp32", "3/4 coding scheme is only in esp32")
    def test_burn_efuse_with_34_coding_scheme(self):
        self._set_34_coding_scheme()
        self.espefuse_py("burn_efuse BLK3_PART_RESERVE 1")
        self.espefuse_py("burn_efuse ADC1_TP_LOW 50")
        self.espefuse_py(
            "burn_efuse ADC1_TP_HIGH 55",
            check_msg="Burn into BLOCK3 is forbidden "
            "(3/4 coding scheme does not allow this)",
            ret_code=2,
        )

    @unittest.skipUnless(chip_target == "esp32", "3/4 coding scheme is only in esp32")
    def test_burn_efuse_with_34_coding_scheme2(self):
        self._set_34_coding_scheme()
        self.espefuse_py("burn_efuse BLK3_PART_RESERVE 1")
        self.espefuse_py(
            "burn_efuse \
            ADC1_TP_LOW 50 \
            ADC1_TP_HIGH 55 \
            ADC2_TP_LOW 40 \
            ADC2_TP_HIGH 45"
        )


class TestBurnKeyCommands(EfuseTestCase):
    @unittest.skipUnless(chip_target == "esp32", "The test only for esp32")
    def test_burn_key_3_key_blocks(self):
        self.espefuse_py("burn_key -h")
        self.espefuse_py(
            "burn_key BLOCK1 images/efuse/192bit",
            check_msg="A fatal error occurred: Incorrect key file size 24. "
            "Key file must be 32 bytes (256 bits) of raw binary key data.",
            ret_code=2,
        )
        self.espefuse_py(
            "burn_key \
            BLOCK1 images/efuse/256bit \
            BLOCK2 images/efuse/256bit_1 \
            BLOCK3 images/efuse/256bit_2 --no-protect-key"
        )
        output = self.espefuse_py("summary -d")
        self.check_data_block_in_log(output, "images/efuse/256bit")
        self.check_data_block_in_log(output, "images/efuse/256bit_1")
        self.check_data_block_in_log(output, "images/efuse/256bit_2")

        self.espefuse_py(
            "burn_key \
            BLOCK1 images/efuse/256bit \
            BLOCK2 images/efuse/256bit_1 \
            BLOCK3 images/efuse/256bit_2"
        )
        output = self.espefuse_py("summary -d")
        self.check_data_block_in_log(output, "images/efuse/256bit")
        self.check_data_block_in_log(output, "images/efuse/256bit_1")
        self.check_data_block_in_log(output, "images/efuse/256bit_2")

    @unittest.skipUnless(chip_target == "esp32c2", "The test only for esp32c2")
    def test_burn_key_1_key_block(self):
        self.espefuse_py("burn_key -h")
        self.espefuse_py(
            "burn_key BLOCK_KEY0 images/efuse/128bit XTS_AES_128_KEY",
            check_msg="A fatal error occurred: Incorrect key file size 16. "
            "Key file must be 32 bytes (256 bits) of raw binary key data.",
            ret_code=2,
        )
        self.espefuse_py(
            "burn_key BLOCK_KEY0 images/efuse/256bit XTS_AES_128_KEY --no-read-protect"
        )
        output = self.espefuse_py("summary -d")
        self.check_data_block_in_log(output, "images/efuse/256bit", reverse_order=True)

        self.espefuse_py("burn_key BLOCK_KEY0 images/efuse/256bit XTS_AES_128_KEY")
        output = self.espefuse_py("summary -d")
        self.assertIn(
            "[3 ] read_regs: 00000000 00000000 00000000 00000000 "
            "00000000 00000000 00000000 00000000",
            output,
        )

    @unittest.skipUnless(chip_target == "esp32c2", "The test only for esp32c2")
    def test_burn_key_one_key_block_with_fe_and_sb_keys(self):
        self.espefuse_py("burn_key -h")
        self.espefuse_py(
            "burn_key BLOCK_KEY0 images/efuse/256bit XTS_AES_128_KEY \
            BLOCK_KEY0 images/efuse/128bit_key SECURE_BOOT_DIGEST",
            check_msg="A fatal error occurred: These keypurposes are incompatible "
            "['XTS_AES_128_KEY', 'SECURE_BOOT_DIGEST']",
            ret_code=2,
        )
        self.espefuse_py(
            "burn_key BLOCK_KEY0 images/efuse/128bit_key "
            "XTS_AES_128_KEY_DERIVED_FROM_128_EFUSE_BITS "
            "BLOCK_KEY0 images/efuse/128bit_key SECURE_BOOT_DIGEST --no-read-protect"
        )
        output = self.espefuse_py("summary -d")
        self.assertIn(
            "[3 ] read_regs: 0c0d0e0f 08090a0b 04050607 00010203 "
            "03020100 07060504 0b0a0908 0f0e0d0c",
            output,
        )

        self.espefuse_py(
            "burn_key BLOCK_KEY0 images/efuse/128bit_key "
            "XTS_AES_128_KEY_DERIVED_FROM_128_EFUSE_BITS "
            "BLOCK_KEY0 images/efuse/128bit_key SECURE_BOOT_DIGEST"
        )
        output = self.espefuse_py("summary -d")
        self.assertIn(
            "[3 ] read_regs: 00000000 00000000 00000000 00000000 "
            "03020100 07060504 0b0a0908 0f0e0d0c",
            output,
        )

    @unittest.skipUnless(
        chip_target
        in ["esp32s2", "esp32s3", "esp32s3beta1", "esp32c3", "esp32h2", "esp32h2beta1"],
        "Only chip with 6 keys",
    )
    def test_burn_key_with_6_keys(self):
        cmd = "burn_key \
               BLOCK_KEY0 images/efuse/256bit   XTS_AES_256_KEY_1 \
               BLOCK_KEY1 images/efuse/256bit_1 XTS_AES_256_KEY_2 \
               BLOCK_KEY2 images/efuse/256bit_2 XTS_AES_128_KEY"
        if chip_target == "esp32c3":
            cmd = cmd.replace("XTS_AES_256_KEY_1", "XTS_AES_128_KEY")
            cmd = cmd.replace("XTS_AES_256_KEY_2", "XTS_AES_128_KEY")
        self.espefuse_py(cmd + " --no-read-protect --no-write-protect")
        output = self.espefuse_py("summary -d")
        self.check_data_block_in_log(output, "images/efuse/256bit", reverse_order=True)
        self.check_data_block_in_log(
            output, "images/efuse/256bit_1", reverse_order=True
        )
        self.check_data_block_in_log(
            output, "images/efuse/256bit_2", reverse_order=True
        )

        self.espefuse_py(cmd)
        output = self.espefuse_py("summary -d")
        self.assertIn(
            "[4 ] read_regs: 00000000 00000000 00000000 00000000 "
            "00000000 00000000 00000000 00000000",
            output,
        )
        self.assertIn(
            "[5 ] read_regs: 00000000 00000000 00000000 00000000 "
            "00000000 00000000 00000000 00000000",
            output,
        )
        self.assertIn(
            "[6 ] read_regs: 00000000 00000000 00000000 00000000 "
            "00000000 00000000 00000000 00000000",
            output,
        )

        self.espefuse_py(
            "burn_key \
            BLOCK_KEY3 images/efuse/256bit   SECURE_BOOT_DIGEST0 \
            BLOCK_KEY4 images/efuse/256bit_1 SECURE_BOOT_DIGEST1 \
            BLOCK_KEY5 images/efuse/256bit_2 SECURE_BOOT_DIGEST2"
        )
        output = self.espefuse_py("summary -d")
        self.check_data_block_in_log(output, "images/efuse/256bit")
        self.check_data_block_in_log(output, "images/efuse/256bit_1")
        self.check_data_block_in_log(output, "images/efuse/256bit_2")

    @unittest.skipUnless(chip_target == "esp32", "3/4 coding scheme is only in esp32")
    def test_burn_key_with_34_coding_scheme(self):
        self._set_34_coding_scheme()
        self.espefuse_py(
            "burn_key BLOCK1 images/efuse/256bit",
            check_msg="A fatal error occurred: Incorrect key file size 32. "
            "Key file must be 24 bytes (192 bits) of raw binary key data.",
            ret_code=2,
        )
        self.espefuse_py(
            "burn_key \
            BLOCK1 images/efuse/192bit \
            BLOCK2 images/efuse/192bit_1 \
            BLOCK3 images/efuse/192bit_2 --no-protect-key"
        )
        output = self.espefuse_py("summary -d")
        self.check_data_block_in_log(output, "images/efuse/192bit")
        self.check_data_block_in_log(output, "images/efuse/192bit_1")
        self.check_data_block_in_log(output, "images/efuse/192bit_2")

        self.espefuse_py(
            "burn_key \
            BLOCK1 images/efuse/192bit \
            BLOCK2 images/efuse/192bit_1 \
            BLOCK3 images/efuse/192bit_2"
        )
        output = self.espefuse_py("summary -d")
        self.check_data_block_in_log(output, "images/efuse/192bit")
        self.check_data_block_in_log(output, "images/efuse/192bit_1")
        self.check_data_block_in_log(output, "images/efuse/192bit_2")

    @unittest.skipUnless(
        chip_target in ["esp32s2", "esp32s3"],
        "512 bit keys are only supported on ESP32-S2 and S3",
    )
    def test_burn_key_512bit(self):
        self.espefuse_py(
            "burn_key \
            BLOCK_KEY0 images/efuse/256bit_1_256bit_2_combined \
            XTS_AES_256_KEY --no-read-protect --no-write-protect"
        )
        output = self.espefuse_py("summary -d")
        self.check_data_block_in_log(
            output, "images/efuse/256bit_1", reverse_order=True
        )
        self.check_data_block_in_log(
            output, "images/efuse/256bit_2", reverse_order=True
        )

    @unittest.skipUnless(
        chip_target in ["esp32s2", "esp32s3"],
        "512 bit keys are only supported on ESP32-S2 and S3",
    )
    def test_burn_key_512bit_non_consecutive_blocks(self):

        # Burn efuses seperately to test different kinds
        # of "key used" detection criteria
        self.espefuse_py(
            "burn_key \
            BLOCK_KEY2 images/efuse/256bit XTS_AES_128_KEY"
        )
        self.espefuse_py(
            "burn_key \
            BLOCK_KEY3 images/efuse/256bit USER --no-read-protect --no-write-protect"
        )
        self.espefuse_py(
            "burn_key \
            BLOCK_KEY4 images/efuse/256bit SECURE_BOOT_DIGEST0"
        )

        self.espefuse_py(
            "burn_key \
            BLOCK_KEY1 images/efuse/256bit_1_256bit_2_combined \
            XTS_AES_256_KEY --no-read-protect --no-write-protect"
        )

        # Second half of key should burn to first available key block (BLOCK_KEY5)
        output = self.espefuse_py("summary -d")
        self.check_data_block_in_log(
            output, "images/efuse/256bit_1", reverse_order=True
        )
        self.check_data_block_in_log(
            output, "images/efuse/256bit_2", reverse_order=True
        )

        self.assertIn(
            "[5 ] read_regs: bcbd11bf b8b9babb b4b5b6b7 "
            "b0b1b2b3 acadaeaf a8a9aaab a4a5a6a7 11a1a2a3",
            output,
        )
        self.assertIn(
            "[9 ] read_regs: bcbd22bf b8b9babb b4b5b6b7 "
            "b0b1b2b3 acadaeaf a8a9aaab a4a5a6a7 22a1a2a3",
            output,
        )

    @unittest.skipUnless(
        chip_target in ["esp32s2", "esp32s3"],
        "512 bit keys are only supported on ESP32-S2 and S3",
    )
    def test_burn_key_512bit_non_consecutive_blocks_loop_around(self):
        self.espefuse_py(
            "burn_key \
            BLOCK_KEY2 images/efuse/256bit XTS_AES_128_KEY \
            BLOCK_KEY3 images/efuse/256bit USER \
            BLOCK_KEY4 images/efuse/256bit SECURE_BOOT_DIGEST0 \
            BLOCK_KEY5 images/efuse/256bit SECURE_BOOT_DIGEST1 \
            BLOCK_KEY1 images/efuse/256bit_1_256bit_2_combined \
            XTS_AES_256_KEY --no-read-protect --no-write-protect"
        )

        # Second half of key should burn to first available key block (BLOCK_KEY0)
        output = self.espefuse_py("summary -d")
        self.check_data_block_in_log(
            output, "images/efuse/256bit_1", reverse_order=True
        )
        self.check_data_block_in_log(
            output, "images/efuse/256bit_2", reverse_order=True
        )

        self.assertIn(
            "[5 ] read_regs: bcbd11bf b8b9babb b4b5b6b7 b0b1b2b3 "
            "acadaeaf a8a9aaab a4a5a6a7 11a1a2a3",
            output,
        )
        self.assertIn(
            "[4 ] read_regs: bcbd22bf b8b9babb b4b5b6b7 b0b1b2b3 "
            "acadaeaf a8a9aaab a4a5a6a7 22a1a2a3",
            output,
        )


class TestBurnBlockDataCommands(EfuseTestCase):
    def test_burn_block_data_check_args(self):
        self.espefuse_py("burn_block_data -h")
        blk0 = "BLOCK0"
        blk1 = "BLOCK1"
        self.espefuse_py(
            "burn_block_data \
            %s images/efuse/224bit \
            %s"
            % (blk0, blk1),
            check_msg="A fatal error occurred: "
            "The number of block_name (2) and datafile (1) should be the same.",
            ret_code=2,
        )

    @unittest.skipUnless(chip_target == "esp32", "The test only for esp32")
    def test_burn_block_data_with_3_key_blocks(self):
        self.espefuse_py(
            "burn_block_data \
            BLOCK0 images/efuse/224bit \
            BLOCK3 images/efuse/256bit"
        )
        output = self.espefuse_py("summary -d")
        self.assertIn(
            "[3 ] read_regs: a3a2a1a0 a7a6a5a4 abaaa9a8 afaeadac "
            "b3b2b1b0 b7b6b5b4 bbbab9b8 bfbebdbc",
            output,
        )
        self.check_data_block_in_log(output, "images/efuse/256bit")

        self.espefuse_py(
            "burn_block_data \
            BLOCK2 images/efuse/256bit_1"
        )
        self.check_data_block_in_log(
            self.espefuse_py("summary -d"), "images/efuse/256bit_1"
        )

        self.espefuse_py(
            "burn_block_data \
            BLOCK1 images/efuse/256bit_2"
        )
        self.check_data_block_in_log(
            self.espefuse_py("summary -d"), "images/efuse/256bit_2"
        )

    @unittest.skipUnless(chip_target == "esp32c2", "The test only for esp32c2")
    def test_burn_block_data_with_1_key_block(self):
        self.espefuse_py(
            "burn_block_data \
            BLOCK0 images/efuse/64bit \
            BLOCK1 images/efuse/96bit \
            BLOCK2 images/efuse/256bit \
            BLOCK3 images/efuse/256bit"
        )
        output = self.espefuse_py("summary -d")
        self.assertIn("[0 ] read_regs: 00000001 0000000c", output)
        self.assertIn("[1 ] read_regs: 03020100 07060504 000a0908", output)
        self.assertIn(
            "[2 ] read_regs: a3a2a1a0 a7a6a5a4 abaaa9a8 afaeadac "
            "b3b2b1b0 b7b6b5b4 bbbab9b8 bfbebdbc",
            output,
        )
        self.assertIn(
            "[3 ] read_regs: a3a2a1a0 a7a6a5a4 abaaa9a8 afaeadac "
            "b3b2b1b0 b7b6b5b4 bbbab9b8 bfbebdbc",
            output,
        )

    @unittest.skipUnless(
        chip_target
        in ["esp32s2", "esp32s3", "esp32s3beta1", "esp32c3", "esp32h2", "esp32h2beta1"],
        "Only chip with 6 keys",
    )
    def test_burn_block_data_with_6_keys(self):
        self.espefuse_py(
            "burn_block_data \
            BLOCK0 images/efuse/192bit \
            BLOCK3 images/efuse/256bit"
        )
        output = self.espefuse_py("summary -d")
        self.assertIn(
            "[0 ] read_regs: 00000000 07060500 00000908 00000000 13000000 00161514",
            output,
        )
        self.assertIn(
            "[3 ] read_regs: a3a2a1a0 a7a6a5a4 abaaa9a8 afaeadac "
            "b3b2b1b0 b7b6b5b4 bbbab9b8 bfbebdbc",
            output,
        )
        self.check_data_block_in_log(output, "images/efuse/256bit")

        self.espefuse_py(
            "burn_block_data \
            BLOCK10 images/efuse/256bit_1"
        )
        self.check_data_block_in_log(
            self.espefuse_py("summary -d"), "images/efuse/256bit_1"
        )

        self.espefuse_py(
            "burn_block_data \
            BLOCK1 images/efuse/192bit \
            BLOCK5 images/efuse/256bit_1 \
            BLOCK6 images/efuse/256bit_2"
        )
        output = self.espefuse_py("summary -d")
        self.assertIn(
            "[1 ] read_regs: 00000000 07060500 00000908 00000000 13000000 00161514",
            output,
        )
        self.check_data_block_in_log(output, "images/efuse/256bit")
        self.check_data_block_in_log(output, "images/efuse/256bit_1", 2)
        self.check_data_block_in_log(output, "images/efuse/256bit_2")

    def test_burn_block_data_check_errors(self):
        self.espefuse_py(
            "burn_block_data \
            BLOCK2 images/efuse/192bit \
            BLOCK2 images/efuse/192bit_1",
            check_msg="A fatal error occurred: Found repeated",
            ret_code=2,
        )
        self.espefuse_py(
            "burn_block_data \
            BLOCK2 images/efuse/192bit \
            BLOCK3 images/efuse/192bit_1 \
            --offset 4",
            check_msg="A fatal error occurred: "
            "The 'offset' option is not applicable when a few blocks are passed.",
            ret_code=2,
        )
        self.espefuse_py(
            "burn_block_data BLOCK0 images/efuse/192bit --offset 33",
            check_msg="A fatal error occurred: Invalid offset: the block0 only holds",
            ret_code=2,
        )
        self.espefuse_py(
            "burn_block_data BLOCK0 images/efuse/256bit --offset 4",
            check_msg="A fatal error occurred: Data does not fit:",
            ret_code=2,
        )

    @unittest.skipUnless(chip_target == "esp32", "The test only for esp32")
    def test_burn_block_data_with_offset_for_3_key_blocks(self):
        offset = 1
        self.espefuse_py(
            "burn_block_data --offset %d BLOCK0 images/efuse/192bit" % offset
        )

        offset = 4
        self.espefuse_py(
            "burn_block_data --offset %d BLOCK1 images/efuse/192bit_1" % (offset)
        )
        self.check_data_block_in_log(
            self.espefuse_py("summary -d"), "images/efuse/192bit_1", offset=offset
        )

        offset = 6
        self.espefuse_py(
            "burn_block_data --offset %d BLOCK2 images/efuse/192bit_2" % (offset)
        )
        self.check_data_block_in_log(
            self.espefuse_py("summary -d"), "images/efuse/192bit_2", offset=offset
        )

        offset = 8
        self.espefuse_py(
            "burn_block_data --offset %d BLOCK3 images/efuse/192bit_2" % (offset)
        )
        self.check_data_block_in_log(
            self.espefuse_py("summary -d"), "images/efuse/192bit_2", offset=offset
        )

    @unittest.skipUnless(chip_target == "esp32c2", "The test only for esp32c2")
    def test_burn_block_data_with_offset_1_key_block(self):
        offset = 4
        self.espefuse_py(
            "burn_block_data --offset %d BLOCK1 images/efuse/92bit" % (offset)
        )
        output = self.espefuse_py("summary -d")
        self.assertIn("[1 ] read_regs: 00000000 03020100 00060504", output)

        offset = 6
        self.espefuse_py(
            "burn_block_data --offset %d BLOCK2 images/efuse/192bit_1" % (offset)
        )
        output = self.espefuse_py("summary -d")
        self.assertIn(
            "[2 ] read_regs: 00000000 00110000 05000000 09080706 "
            "0d0c0b0a 11100f0e 15141312 00002116",
            output,
        )

        offset = 8
        self.espefuse_py(
            "burn_block_data --offset %d BLOCK3 images/efuse/192bit_2" % (offset)
        )
        self.check_data_block_in_log(
            self.espefuse_py("summary -d"), "images/efuse/192bit_2", offset=offset
        )

    @unittest.skipUnless(
        chip_target
        in ["esp32s2", "esp32s3", "esp32s3beta1", "esp32c3", "esp32h2", "esp32h2beta1"],
        "Only chip with 6 keys",
    )
    def test_burn_block_data_with_offset_6_keys(self):
        offset = 4
        self.espefuse_py(
            "burn_block_data --offset %s BLOCK_KEY0 images/efuse/192bit_1" % (offset)
        )
        self.check_data_block_in_log(
            self.espefuse_py("summary -d"), "images/efuse/192bit_1", offset=offset
        )

        offset = 6
        self.espefuse_py(
            "burn_block_data --offset %s BLOCK_KEY1 images/efuse/192bit_2" % (offset)
        )
        self.check_data_block_in_log(
            self.espefuse_py("summary -d"), "images/efuse/192bit_2", offset=offset
        )

        offset = 8
        self.espefuse_py(
            "burn_block_data --offset %s BLOCK_KEY2 images/efuse/192bit_2" % (offset)
        )
        self.check_data_block_in_log(
            self.espefuse_py("summary -d"), "images/efuse/192bit_2", offset=offset
        )

    @unittest.skipUnless(chip_target == "esp32", "3/4 coding scheme is only in esp32")
    def test_burn_block_data_with_34_coding_scheme(self):
        self._set_34_coding_scheme()
        self.espefuse_py(
            "burn_block_data BLOCK1 images/efuse/256bit",
            check_msg="A fatal error occurred: Data does not fit: "
            "the block1 size is 24 bytes, data file is 32 bytes, offset 0",
            ret_code=2,
        )

        self.espefuse_py(
            "burn_block_data \
            BLOCK1 images/efuse/192bit \
            BLOCK2 images/efuse/192bit_1 \
            BLOCK3 images/efuse/192bit_2"
        )
        output = self.espefuse_py("summary -d")
        self.check_data_block_in_log(output, "images/efuse/192bit")
        self.check_data_block_in_log(output, "images/efuse/192bit_1")
        self.check_data_block_in_log(output, "images/efuse/192bit_2")

    @unittest.skipUnless(chip_target == "esp32", "3/4 coding scheme is only in esp32")
    def test_burn_block_data_with_34_coding_scheme_and_offset(self):
        self._set_34_coding_scheme()

        offset = 4
        self.espefuse_py(
            "burn_block_data --offset %d BLOCK1 images/efuse/128bit" % (offset)
        )
        self.check_data_block_in_log(
            self.espefuse_py("summary -d"), "images/efuse/128bit", offset=offset
        )

        offset = 6
        self.espefuse_py(
            "burn_block_data --offset %d BLOCK2 images/efuse/128bit" % (offset)
        )
        self.check_data_block_in_log(
            self.espefuse_py("summary -d"), "images/efuse/128bit", offset=offset
        )

        offset = 8
        self.espefuse_py(
            "burn_block_data --offset %d BLOCK3 images/efuse/128bit" % (offset)
        )
        self.check_data_block_in_log(
            self.espefuse_py("summary -d"), "images/efuse/128bit", offset=offset
        )


@unittest.skipUnless(
    chip_target == "esp32", "The test only for esp32, supports 2 key blocks"
)
class TestBurnKeyDigestCommandsEsp32(EfuseTestCase):
    def test_burn_key_digest(self):
        self.espefuse_py("burn_key_digest -h")
        esp = self.get_esptool()
        if "revision 3" in esp.get_chip_description():
            self.espefuse_py(
                "burn_key_digest secure_images/rsa_secure_boot_signing_key.pem"
            )
            output = self.espefuse_py("summary -d")
            self.assertIn(
                " = cb 27 91 a3 71 b0 c0 32 2b f7 37 04 78 ba 09 62 "
                "22 4c ab 1c f2 28 78 79 e4 29 67 3e 7d a8 44 63 R/-",
                output,
            )
        else:
            self.espefuse_py(
                "burn_key_digest secure_images/rsa_secure_boot_signing_key.pem",
                check_msg="Incorrect chip revision for Secure boot v2.",
                ret_code=2,
            )

    def test_burn_key_from_digest(self):
        # python espsecure.py digest_rsa_public_key
        # --keyfile test/secure_images/rsa_secure_boot_signing_key.pem
        # -o secure_images/rsa_public_key_digest.bin
        self.espefuse_py(
            "burn_key \
            BLOCK2 secure_images/rsa_public_key_digest.bin --no-protect-key"
        )
        output = self.espefuse_py("summary -d")
        self.assertEqual(
            1,
            output.count(
                " = cb 27 91 a3 71 b0 c0 32 2b f7 37 04 78 ba 09 62 "
                "22 4c ab 1c f2 28 78 79 e4 29 67 3e 7d a8 44 63 R/W"
            ),
        )

    def test_burn_key_digest_with_34_coding_scheme(self):
        self._set_34_coding_scheme()
        self.espefuse_py(
            "burn_key_digest secure_images/rsa_secure_boot_signing_key.pem",
            check_msg="burn_key_digest only works with 'None' coding scheme",
            ret_code=2,
        )


@unittest.skipUnless(
    chip_target == "esp32c2", "The test only for esp32c2, supports one key block"
)
class TestBurnKeyDigestCommandsEsp32C2(EfuseTestCase):
    def test_burn_key_digest1(self):
        # python espsecure.py generate_signing_key --version 2
        # secure_images/ecdsa192_secure_boot_signing_key_v2.pem   --scheme ecdsa192
        self.espefuse_py("burn_key_digest -h")
        self.espefuse_py(
            "burn_key_digest secure_images/ecdsa192_secure_boot_signing_key_v2.pem"
        )
        output = self.espefuse_py("summary -d")
        self.assertIn(" = 1e 3d 15 16 96 ca 7f 22 a6 e8 8b d5 27 a0 3b 3b R/-", output)
        self.assertIn(
            " = 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 "
            "1e 3d 15 16 96 ca 7f 22 a6 e8 8b d5 27 a0 3b 3b R/-",
            output,
        )

    def test_burn_key_digest2(self):
        # python espsecure.py generate_signing_key --version 2
        # secure_images/ecdsa256_secure_boot_signing_key_v2.pem   --scheme ecdsa256
        self.espefuse_py("burn_key_digest -h")
        self.espefuse_py(
            "burn_key_digest secure_images/ecdsa256_secure_boot_signing_key_v2.pem"
        )
        output = self.espefuse_py("summary -d")
        self.assertIn(" = bf 0f 6a f6 8b d3 6d 8b 53 b3 da a9 33 f6 0a 04 R/-", output)
        self.assertIn(
            " = 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 "
            "bf 0f 6a f6 8b d3 6d 8b 53 b3 da a9 33 f6 0a 04 R/-",
            output,
        )

    def test_burn_key_from_digest1(self):
        # python espsecure.py digest_sbv2_public_key --keyfile
        # secure_images/ecdsa192_secure_boot_signing_key_v2.pem
        # -o secure_images/ecdsa192_public_key_digest_v2.bin
        self.espefuse_py(
            "burn_key BLOCK_KEY0 "
            "secure_images/ecdsa192_public_key_digest_v2.bin SECURE_BOOT_DIGEST"
        )
        output = self.espefuse_py("summary -d")
        self.assertIn(
            " = 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 "
            "1e 3d 15 16 96 ca 7f 22 a6 e8 8b d5 27 a0 3b 3b R/-",
            output,
        )

    def test_burn_key_from_digest2(self):
        # python espsecure.py digest_sbv2_public_key --keyfile
        # secure_images/ecdsa256_secure_boot_signing_key_v2.pem
        # -o secure_images/ecdsa256_public_key_digest_v2.bin
        self.espefuse_py(
            "burn_key BLOCK_KEY0 "
            "secure_images/ecdsa256_public_key_digest_v2.bin SECURE_BOOT_DIGEST"
        )
        output = self.espefuse_py("summary -d")
        self.assertIn(
            " = 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 "
            "bf 0f 6a f6 8b d3 6d 8b 53 b3 da a9 33 f6 0a 04 R/-",
            output,
        )


@unittest.skipUnless(
    chip_target
    in ["esp32s2", "esp32s3", "esp32s3beta1", "esp32c3", "esp32h2", "esp32h2beta1"],
    "Supports 6 key blocks",
)
class TestBurnKeyDigestCommands(EfuseTestCase):
    def test_burn_key_digest(self):
        self.espefuse_py("burn_key_digest -h")
        self.espefuse_py(
            "burn_key_digest \
            BLOCK_KEY0 \
            secure_images/rsa_secure_boot_signing_key.pem SECURE_BOOT_DIGEST0 \
            BLOCK_KEY1 \
            secure_images/rsa_secure_boot_signing_key2.pem SECURE_BOOT_DIGEST1 \
            BLOCK_KEY2 ",
            check_msg="A fatal error occurred: The number of blocks (3), "
            "datafile (2) and keypurpose (2) should be the same.",
            ret_code=2,
        )
        self.espefuse_py(
            "burn_key_digest \
            BLOCK_KEY0 \
            secure_images/rsa_secure_boot_signing_key.pem SECURE_BOOT_DIGEST0 \
            BLOCK_KEY1 \
            secure_images/rsa_secure_boot_signing_key2.pem SECURE_BOOT_DIGEST1 \
            BLOCK_KEY2 \
            secure_images/rsa_secure_boot_signing_key2.pem SECURE_BOOT_DIGEST2"
        )
        output = self.espefuse_py("summary -d")
        self.assertEqual(
            1,
            output.count(
                " = cb 27 91 a3 71 b0 c0 32 2b f7 37 04 78 ba 09 62 "
                "22 4c ab 1c f2 28 78 79 e4 29 67 3e 7d a8 44 63 R/-"
            ),
        )
        self.assertEqual(
            2,
            output.count(
                " = 90 1a 74 09 23 8d 52 d4 cb f9 6f 56 3f b3 f4 29 "
                "6d ab d6 6a 33 f5 3b 15 ee cd 8c b3 e7 ec 45 d3 R/-"
            ),
        )

    def test_burn_key_from_digest(self):
        #  python espsecure.py digest_rsa_public_key
        # --keyfile test/secure_images/rsa_secure_boot_signing_key.pem
        # -o secure_images/rsa_public_key_digest.bin
        self.espefuse_py(
            "burn_key \
            BLOCK_KEY0 secure_images/rsa_public_key_digest.bin SECURE_BOOT_DIGEST0"
        )
        output = self.espefuse_py("summary -d")
        self.assertEqual(
            1,
            output.count(
                " = cb 27 91 a3 71 b0 c0 32 2b f7 37 04 78 ba 09 62 "
                "22 4c ab 1c f2 28 78 79 e4 29 67 3e 7d a8 44 63 R/-"
            ),
        )

        self.espefuse_py(
            "burn_key_digest \
            BLOCK_KEY1 \
            secure_images/rsa_secure_boot_signing_key.pem SECURE_BOOT_DIGEST1"
        )
        output = self.espefuse_py("summary -d")
        self.assertEqual(
            2,
            output.count(
                " = cb 27 91 a3 71 b0 c0 32 2b f7 37 04 78 ba 09 62 "
                "22 4c ab 1c f2 28 78 79 e4 29 67 3e 7d a8 44 63 R/-"
            ),
        )


class TestBurnBitCommands(EfuseTestCase):
    @unittest.skipUnless(chip_target == "esp32", "The test only for esp32")
    def test_burn_bit_for_chips_with_3_key_blocks(self):
        self.espefuse_py("burn_bit -h")
        self.espefuse_py("burn_bit BLOCK3 0 1 2 4 8 16 32 64 96 128 160 192 224 255")
        self.espefuse_py(
            "summary",
            check_msg="17 01 01 00 01 00 00 00 01 00 00 00 01 00 00 "
            "00 01 00 00 00 01 00 00 00 01 00 00 00 01 00 00 80",
        )

        self.espefuse_py(
            "burn_bit BLOCK3 3 5 6 7 9 10 11 12 13 14 15 31 63 95 127 159 191 223 254"
        )
        self.espefuse_py(
            "summary",
            check_msg="ff ff 01 80 01 00 00 80 01 00 00 80 01 "
            "00 00 80 01 00 00 80 01 00 00 80 01 00 00 80 01 00 00 c0",
        )

    @unittest.skipUnless(chip_target == "esp32c2", "The test only for esp32c2")
    def test_burn_bit_for_chips_with_1_key_block(self):
        self.espefuse_py("burn_bit -h")
        self.espefuse_py("burn_bit BLOCK3 0 1 2 4 8 16 32 64 96 128 160 192 224 255")
        self.espefuse_py(
            "summary",
            check_msg="17 01 01 00 01 00 00 00 01 00 00 00 01 00 "
            "00 00 01 00 00 00 01 00 00 00 01 00 00 00 01 00 00 80",
        )
        self.espefuse_py(
            "burn_bit BLOCK3 100",
            check_msg="Burn into BLOCK_KEY0 is forbidden "
            "(RS coding scheme does not allow this)",
            ret_code=2,
        )

        self.espefuse_py("burn_bit BLOCK0 0 1 2")
        self.espefuse_py("summary", check_msg="[0 ] read_regs: 00000007 00000000")

    @unittest.skipUnless(
        chip_target
        in ["esp32s2", "esp32s3", "esp32s3beta1", "esp32c3", "esp32h2", "esp32h2beta1"],
        "Only chip with 6 keys",
    )
    def test_burn_bit_for_chips_with_6_key_blocks(self):
        self.espefuse_py("burn_bit -h")
        self.espefuse_py("burn_bit BLOCK3 0 1 2 4 8 16 32 64 96 128 160 192 224 255")
        self.espefuse_py(
            "summary",
            check_msg="17 01 01 00 01 00 00 00 01 00 00 00 01 00 "
            "00 00 01 00 00 00 01 00 00 00 01 00 00 00 01 00 00 80",
        )
        self.espefuse_py(
            "burn_bit BLOCK3 100",
            check_msg="Burn into BLOCK_USR_DATA is forbidden "
            "(RS coding scheme does not allow this)",
            ret_code=2,
        )

        self.espefuse_py("burn_bit BLOCK0 13")
        self.espefuse_py(
            "summary",
            check_msg="[0 ] read_regs: 00002000 00000000 00000000 "
            "00000000 00000000 00000000",
        )

        self.espefuse_py("burn_bit BLOCK0 24")
        self.espefuse_py(
            "summary",
            check_msg="[0 ] read_regs: 01002000 00000000 00000000 "
            "00000000 00000000 00000000",
        )

    @unittest.skipUnless(chip_target == "esp32", "3/4 coding scheme is only in esp32")
    def test_burn_bit_with_34_coding_scheme(self):
        self._set_34_coding_scheme()
        self.espefuse_py("burn_bit BLOCK3 0 1 2 4 8 16 32 64 96 128 160 191")
        self.espefuse_py(
            "summary",
            check_msg="17 01 01 00 01 00 00 00 01 00 00 00 01 00 "
            "00 00 01 00 00 00 01 00 00 80",
        )
        self.espefuse_py(
            "burn_bit BLOCK3 17",
            check_msg="Burn into BLOCK3 is forbidden "
            "(3/4 coding scheme does not allow this).",
            ret_code=2,
        )


@unittest.skipUnless(
    chip_target == "esp32", "Tests are only for esp32. (TODO: add for all chips)"
)
class TestByteOrderBurnKeyCommand(EfuseTestCase):
    def test_1_secure_boot_v1(self):
        if chip_target == "esp32":
            self.espefuse_py(
                "burn_key \
                flash_encryption images/efuse/256bit \
                secure_boot_v1 images/efuse/256bit_1 --no-protect-key"
            )
            output = self.espefuse_py("summary -d")
            self.check_data_block_in_log(
                output, "images/efuse/256bit", reverse_order=True
            )
            self.check_data_block_in_log(
                output, "images/efuse/256bit_1", reverse_order=True
            )

            self.espefuse_py(
                "burn_key \
                flash_encryption  images/efuse/256bit \
                secure_boot_v1    images/efuse/256bit_1"
            )
            output = self.espefuse_py("summary -d")
            self.assertIn(
                "[1 ] read_regs: 00000000 00000000 00000000 00000000 "
                "00000000 00000000 00000000 00000000",
                output,
            )
            self.assertIn(
                "[2 ] read_regs: 00000000 00000000 00000000 00000000 "
                "00000000 00000000 00000000 00000000",
                output,
            )
            self.assertIn(
                "[3 ] read_regs: 00000000 00000000 00000000 00000000 "
                "00000000 00000000 00000000 00000000",
                output,
            )

    def test_2_secure_boot_v1(self):
        if chip_target == "esp32":
            self.espefuse_py(
                "burn_key \
                flash_encryption images/efuse/256bit \
                secure_boot_v2 images/efuse/256bit_1 --no-protect-key"
            )
            output = self.espefuse_py("summary -d")
            self.check_data_block_in_log(
                output, "images/efuse/256bit", reverse_order=True
            )
            self.check_data_block_in_log(
                output, "images/efuse/256bit_1", reverse_order=False
            )

            self.espefuse_py(
                "burn_key \
                flash_encryption images/efuse/256bit \
                secure_boot_v2 images/efuse/256bit_1"
            )
            output = self.espefuse_py("summary -d")
            self.assertIn(
                "[1 ] read_regs: 00000000 00000000 00000000 00000000 "
                "00000000 00000000 00000000 00000000",
                output,
            )
            self.check_data_block_in_log(
                output, "images/efuse/256bit_1", reverse_order=False
            )


class TestExecuteScriptsCommands(EfuseTestCase):
    @unittest.skipIf(chip_target == "esp32c2", "TODO: Add tests for esp32c2")
    def test_execute_scripts_with_check_that_only_one_burn(self):
        self.espefuse_py("execute_scripts -h")
        name = chip_target if chip_target in ["esp32", "esp32c2"] else "esp32xx"
        os.chdir(os.path.join(TEST_DIR, "efuse_scripts", name))
        self.espefuse_py("execute_scripts test_efuse_script2.py")
        os.chdir(TEST_DIR)

    @unittest.skipIf(chip_target == "esp32c2", "TODO: Add tests for esp32c2")
    def test_execute_scripts_with_check(self):
        self.espefuse_py("execute_scripts -h")
        name = chip_target if chip_target in ["esp32", "esp32c2"] else "esp32xx"
        os.chdir(os.path.join(TEST_DIR, "efuse_scripts", name))
        self.espefuse_py("execute_scripts test_efuse_script.py")
        os.chdir(TEST_DIR)

    def test_execute_scripts_with_index_and_config(self):
        if chip_target in ["esp32", "esp32c2"]:
            cmd = "execute_scripts efuse_scripts/efuse_burn1.py --index 10 \
            --configfiles efuse_scripts/esp32/config1.json"
        else:
            cmd = "execute_scripts efuse_scripts/efuse_burn1.py --index 10 \
            --configfiles efuse_scripts/esp32xx/config1.json"
        self.espefuse_py(cmd)
        output = self.espefuse_py("summary -d")
        if chip_target in ["esp32", "esp32c2"]:
            self.assertIn(
                "[3 ] read_regs: e00007ff 00000000 00000000 00000000 "
                "00000000 00000000 00000000 00000000",
                output,
            )
        else:
            self.assertIn(
                "[8 ] read_regs: e00007ff 00000000 00000000 00000000 "
                "00000000 00000000 00000000 00000000",
                output,
            )

    def test_execute_scripts_nesting(self):
        if chip_target in ["esp32", "esp32c2"]:
            cmd = "execute_scripts efuse_scripts/efuse_burn2.py --index 28 \
            --configfiles efuse_scripts/esp32/config2.json"
        else:
            cmd = "execute_scripts efuse_scripts/efuse_burn2.py --index 28 \
            --configfiles efuse_scripts/esp32xx/config2.json"
        self.espefuse_py(cmd)
        output = self.espefuse_py("summary -d")
        if chip_target in ["esp32", "esp32c2"]:
            self.assertIn(
                "[2 ] read_regs: 10000000 00000000 00000000 00000000 "
                "00000000 00000000 00000000 00000000",
                output,
            )
            self.assertIn(
                "[3 ] read_regs: ffffffff 00000000 00000000 00000000 "
                "00000000 00000000 00000000 00000000",
                output,
            )
        else:
            self.assertIn(
                "[7 ] read_regs: 10000000 00000000 00000000 00000000 "
                "00000000 00000000 00000000 00000000",
                output,
            )
            self.assertIn(
                "[8 ] read_regs: ffffffff 00000000 00000000 00000000 "
                "00000000 00000000 00000000 00000000",
                output,
            )


class TestMultipleCommands(EfuseTestCase):
    def test_multiple_cmds_help(self):
        if chip_target == "esp32c2":
            command1 = (
                "burn_key_digest secure_images/ecdsa256_secure_boot_signing_key_v2.pem"
            )
            command2 = "burn_key BLOCK_KEY0 images/efuse/128bit_key \
            XTS_AES_128_KEY_DERIVED_FROM_128_EFUSE_BITS"
        elif chip_target == "esp32":
            command1 = "burn_key_digest secure_images/rsa_secure_boot_signing_key.pem"
            command2 = "burn_key flash_encryption images/efuse/256bit"
        else:
            command1 = "burn_key_digest BLOCK_KEY0 \
            secure_images/rsa_secure_boot_signing_key.pem SECURE_BOOT_DIGEST0"
            command2 = "burn_key BLOCK_KEY0 \
            secure_images/rsa_public_key_digest.bin SECURE_BOOT_DIGEST0"

        self.espefuse_py(
            "-h {cmd1} {cmd2}".format(cmd1=command1, cmd2=command2),
            check_msg="usage: __init__.py [-h]",
        )

        self.espefuse_py(
            "{cmd1} -h {cmd2}".format(cmd1=command1, cmd2=command2),
            check_msg="usage: __init__.py burn_key_digest [-h]",
        )

        self.espefuse_py(
            "{cmd1} {cmd2} -h".format(cmd1=command1, cmd2=command2),
            check_msg="usage: __init__.py burn_key [-h]",
        )

    @unittest.skipUnless(
        chip_target == "esp32c2", "For this chip, FE and SB keys go into one BLOCK"
    )
    def test_1_esp32c2(self):
        self.espefuse_py(
            "burn_key_digest secure_images/ecdsa256_secure_boot_signing_key_v2.pem \
            burn_key BLOCK_KEY0 images/efuse/128bit_key \
            XTS_AES_128_KEY_DERIVED_FROM_128_EFUSE_BITS --no-read-protect \
            summary"
        )
        output = self.espefuse_py("summary -d")
        self.assertIn(
            "[3 ] read_regs: 0c0d0e0f 08090a0b 04050607 00010203 "
            "f66a0fbf 8b6dd38b a9dab353 040af633",
            output,
        )
        self.assertIn(" = 0f 0e 0d 0c 0b 0a 09 08 07 06 05 04 03 02 01 00 R/-", output)
        self.assertIn(" = bf 0f 6a f6 8b d3 6d 8b 53 b3 da a9 33 f6 0a 04 R/-", output)

    @unittest.skipUnless(
        chip_target == "esp32c2", "For this chip, FE and SB keys go into one BLOCK"
    )
    def test_2_esp32c2(self):
        self.espefuse_py(
            "burn_key_digest secure_images/ecdsa256_secure_boot_signing_key_v2.pem \
            burn_key BLOCK_KEY0 \
            images/efuse/128bit_key XTS_AES_128_KEY_DERIVED_FROM_128_EFUSE_BITS \
            summary"
        )
        output = self.espefuse_py("summary -d")
        self.assertIn(
            "[3 ] read_regs: 00000000 00000000 00000000 00000000 "
            "f66a0fbf 8b6dd38b a9dab353 040af633",
            output,
        )
        self.assertIn(" = ?? ?? ?? ?? ?? ?? ?? ?? ?? ?? ?? ?? ?? ?? ?? ?? -/-", output)
        self.assertIn(" = bf 0f 6a f6 8b d3 6d 8b 53 b3 da a9 33 f6 0a 04 R/-", output)

    def test_burn_bit(self):
        if chip_target == "esp32":
            self._set_34_coding_scheme()
        self.espefuse_py(
            "burn_bit BLOCK2 0 1 2 3 \
            burn_bit BLOCK2 4 5 6 7 \
            burn_bit BLOCK2 8 9 10 11 \
            burn_bit BLOCK2 12 13 14 15 \
            summary"
        )
        output = self.espefuse_py("summary -d")
        self.assertIn("[2 ] read_regs: 0000ffff 00000000", output)

    def test_not_burn_cmds(self):
        self.espefuse_py(
            "summary \
            dump \
            get_custom_mac \
            adc_info \
            check_error"
        )


if __name__ == "__main__":
    if len(sys.argv) > 1:
        chip_target = sys.argv[1]
        if chip_target not in support_list_chips:
            print("Usage: %s - a wrong name of chip" % chip_target)
            sys.exit(1)
        if len(sys.argv) > 3:
            espefuse_port = sys.argv[2]
            reset_port = serial.Serial(sys.argv[3], 115200)
    else:
        chip_target = support_list_chips[0]  # ESP32 by default
    print("HOST_TEST of espefuse.py for %s" % chip_target)

    # unittest also uses argv, so trim the args we used
    sys.argv = [sys.argv[0]] + sys.argv[4:]
    print("Running espefuse.py tests...")
    unittest.main(buffer=True)
