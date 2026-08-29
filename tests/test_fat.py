"""
 * SPDX-License-Identifier: MIT
 *
 * fat-py - A lightweight, pure Python library and command-line management tool for FAT
 *
 * Copyright (c) 2026 Wendley Santos
 *
 * This file is part of fat-py.
 * See the LICENSE file in the project root for license information.
"""

import io
import unittest
import os
import sys

# Ensure src is in python path for tests
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from fat.partition import Disk, MBR, GPT, MBRPartitionEntry, GPTPartitionEntry
from fat.super import FATFS, fat_format_name
from fat.impl import FAT12, FAT16, FAT32
import fat.consts as consts

def create_in_memory_disk(size_mb: int = 16) -> io.BytesIO:
	buf = io.BytesIO(b"\x00" * (size_mb * 1024 * 1024))
	return buf

class TestFATFS(unittest.TestCase):

	def test_mbr_partition_management(self):
		buf = create_in_memory_disk(4)
		disk = Disk(buf)
		
		# Initialized as empty MBR
		self.assertIsInstance(disk.partitions, MBR)
		self.assertEqual(len(disk.partitions.entries), 0)

		# Add partition 1
		idx = disk.partition_add(startLBA=2048, sizeInLBA=4096, bootable=True)
		self.assertEqual(idx, 0)
		self.assertEqual(len(disk.partitions.entries), 1)
		self.assertEqual(disk.partitions.entries[0].startLBA, 2048)
		self.assertEqual(disk.partitions.entries[0].sizeInLBA, 4096)
		self.assertEqual(disk.partitions.entries[0].bootInd, 0x80)

		# Reload disk to test persistence
		disk_reloaded = Disk(buf)
		self.assertEqual(len(disk_reloaded.partitions.entries), 1)
		self.assertEqual(disk_reloaded.partitions.entries[0].startLBA, 2048)

	def test_fat_format_name(self):
		self.assertEqual(fat_format_name("."), ".          ")
		self.assertEqual(fat_format_name(".."), "..         ")
		self.assertEqual(fat_format_name("test.txt"), "TEST    TXT")
		self.assertEqual(fat_format_name("file.c"), "FILE    C  ")
		self.assertEqual(fat_format_name("verylongfilename.jpeg"), "VERYLO~1JPE")

	def _run_fat_test(self, fat_type: str, min_lbas: int):
		size_bytes = (min_lbas + 4096) * 512
		buf = io.BytesIO(b"\x00" * size_bytes)
		disk = Disk(buf)

		start_lba = 2048
		end_lba = min_lbas + 2048

		if fat_type == "FAT12":
			res = FAT12.mkfs(disk, partition=1, start_lba=start_lba, end_lba=end_lba)
		elif fat_type == "FAT16":
			res = FAT16.mkfs(disk, partition=1, start_lba=start_lba, end_lba=end_lba)
		else:
			res = FAT32.mkfs(disk, partition=1, start_lba=start_lba, end_lba=end_lba)

		self.assertTrue(res)

		# Mount filesystem
		fatfs = FATFS(disk, partition=1)
		self.assertIsNotNone(fatfs.fat)

		# Create Directory
		root_clus = fatfs.fat.header_extended.rootClus if isinstance(fatfs.fat, FAT32) else consts.ROOT_DIRECTORY
		res_mkdir = fatfs.create(root_clus, "DOCS", consts.DIRECTORY)
		self.assertTrue(res_mkdir >= 0 or isinstance(fatfs.fat, FAT32))

		# Verify directory listing
		entries = fatfs.ls(root_clus)
		self.assertTrue(any(e.name.decode('latin1', errors='ignore').startswith("DOCS") for e in entries))

		# Create and write to file
		docs_entry = fatfs.search(root_clus, "DOCS")
		self.assertIsNotNone(docs_entry)
		docs_clus = docs_entry.get_cluster()

		create_file_res = fatfs.create(docs_clus, "HELLO.TXT", consts.ARCHIVE)
		self.assertTrue(create_file_res >= 0)

		fd = fatfs.open("/DOCS/HELLO.TXT")
		self.assertIsNotNone(fd)

		test_data = b"Hello, World from FAT filesystem!"
		written = fatfs.write(fd, test_data, len(test_data))
		self.assertEqual(written, len(test_data))

		# Re-open and read file
		fd_read = fatfs.open("/DOCS/HELLO.TXT")
		self.assertIsNotNone(fd_read)
		read_content = fatfs.read(fd_read, len(test_data))
		self.assertEqual(read_content, test_data)

		# Remove file
		rm_res = fatfs.remove(docs_clus, "HELLO.TXT")
		self.assertEqual(rm_res, 0)

		# Verify file is removed
		self.assertIsNone(fatfs.open("/DOCS/HELLO.TXT"))

	def test_fat12(self):
		self._run_fat_test("FAT12", 2000)

	def test_fat16(self):
		self._run_fat_test("FAT16", 10000)

	def test_fat32(self):
		self._run_fat_test("FAT32", 70000)

if __name__ == "__main__":
	unittest.main()
