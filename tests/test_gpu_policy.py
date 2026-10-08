from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from local_coder import gpu_policy

AMD="GPU0:\n vendorID = 0x1002\n deviceType = PHYSICAL_DEVICE_TYPE_DISCRETE_GPU\n deviceName = AMD Radeon RX 6600 (RADV NAVI23)\n"
NV="GPU1:\n vendorID = 0x10de\n deviceType = PHYSICAL_DEVICE_TYPE_DISCRETE_GPU\n deviceName = NVIDIA GeForce GTX 1050 Ti\n"

class GPUPolicyTests(unittest.TestCase):
    def test_vfio_and_reservation_override_visible_nvidia(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);p=root/'0000:04:00.0';p.mkdir()
            for name,value in [('vendor','0x10de'),('device','0x1c82'),('class','0x030000')]:p.joinpath(name).write_text(value)
            driver=root/'vfio-pci';driver.mkdir();p.joinpath('driver').symlink_to(driver)
            with patch.object(gpu_policy,'RESERVED',root/'reserved'):
                self.assertEqual(gpu_policy.inspect(root,AMD+NV)['mode'],'rx6600-ram')
                p.joinpath('driver').unlink();driver=root/'nouveau';driver.mkdir();p.joinpath('driver').symlink_to(driver)
                self.assertEqual(gpu_policy.inspect(root,AMD+NV)['mode'],'dual-vulkan')
                root.joinpath('reserved').touch()
                self.assertEqual(gpu_policy.inspect(root,AMD+NV)['mode'],'rx6600-ram')
    def test_no_nvidia_render_device_keeps_single_gpu(self):
        with tempfile.TemporaryDirectory() as d:
            with patch.object(gpu_policy,'RESERVED',Path(d)/'reserved'):
                self.assertEqual(gpu_policy.inspect(Path(d),AMD)['selected_indices'],[0])

if __name__=='__main__':unittest.main()
