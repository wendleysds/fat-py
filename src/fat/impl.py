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

import fat.datatypes as types
import fat.consts as consts
from fat.partition import Disk
from fat.datatypes import FAT
from array import array
import struct

class FAT32(FAT):
	def __init__(
		self,
		header_boot: types.FATBootHeader,
		header_extended: types.FAT32ExtendedHeader,
		dev: Disk,
		start_lba: int,
		table: array,
		totalClusters: int,
		firstDataSector: int,
		clusterSize: int,
		fsinfo: types.FAT32FSInfo,
	):
		super().__init__(
			header_boot,
			header_extended,
			dev,
			start_lba,
			table,
			totalClusters,
			firstDataSector,
			clusterSize,
		)
		self.fsInfo = fsinfo

	@staticmethod
	def mkfs(disk: Disk, partition: int, start_lba: int, end_lba: int) -> bool:
		start_lba, size_in_lba = FAT._prepare_partition(
			disk, partition, start_lba, end_lba, min_size=2048, mbr_type=0x0C
		)

		bytesPerSec = 512
		secPerClus = 8
		if size_in_lba > 67108864:  # > 32GB
			secPerClus = 64
		elif size_in_lba > 33554432:  # > 16GB
			secPerClus = 32
		elif size_in_lba > 16777216:  # > 8GB
			secPerClus = 16

		while (size_in_lba // secPerClus) < 65525 and secPerClus > 1:
			secPerClus //= 2

		rsvdSecCnt = 32
		numFATs = 2

		hboot = types.FATBootHeader(
			jmpBoot=b"\xEB\x58\x90",
			OEMName=b"MSWIN4.1",
			bytesPerSec=bytesPerSec,
			secPerClus=secPerClus,
			rsvdSecCnt=rsvdSecCnt,
			numFATs=numFATs,
			rootEntCnt=0,
			totSec16=0,
			mediaType=0xF8,
			FATSz16=0,
			secPerTrk=63,
			numHeads=16,
			hiddSec=start_lba,
			totSec32=size_in_lba,
		)

		hextended = types.FAT32ExtendedHeader(
			FATSz32=0,
			extFlags=0,
			FSVer=0,
			rootClus=2,
			FSInfo=1,
			BkBootSec=6,
			reserved=b"\x00" * 12,
			drvNum=0x80,
			reserved1=0,
			bootSig=0x29,
			volID=0xCAFEBAB1,
			volLab=b"NOVA    VOL",
			filSysType=b"FAT32   ",
		)

		tmpVal1 = size_in_lba - hboot.rsvdSecCnt
		tmpVal2 = (128 * hboot.secPerClus) + hboot.numFATs
		fatSz32 = (tmpVal1 + (tmpVal2 - 1)) // tmpVal2
		hextended.FATSz32 = fatSz32

		fatStartSector = hboot.rsvdSecCnt
		fatBytes = fatSz32 * bytesPerSec
		firstDataSector = hboot.rsvdSecCnt + (hboot.numFATs * fatSz32)
		totalClusters = (size_in_lba - firstDataSector) // hboot.secPerClus

		table = bytearray(fatBytes)
		table[0:4] = b"\xF8\xFF\xFF\x0F"
		table[4:8] = b"\xFF\xFF\xFF\x0F"
		table[8:12] = b"\xFF\xFF\xFF\x0F"

		def lba(sec):
			return start_lba + sec

		# 1. Write Boot Sector & Backup
		boot_sector = bytearray(512)
		boot_sector[0:90] = hboot.to_bytes() + hextended.to_bytes()
		boot_sector[510:512] = b"\x55\xAA"
		disk.write(lba(0), boot_sector)
		disk.write(lba(hextended.BkBootSec), boot_sector)

		# 2. Write FSInfo Sector
		fsinfo = types.FAT32FSInfo.create_default(
			free_count=totalClusters - 1, next_free=3
		)
		disk.write(lba(hextended.FSInfo), fsinfo.to_bytes())

		# 3. Write FAT1 and FAT2
		disk.write(lba(fatStartSector), table)
		disk.write(lba(fatStartSector + fatSz32), table)

		# 4. Zero Root Cluster
		root_offset = firstDataSector + ((hextended.rootClus - 2) * secPerClus)
		disk.write(lba(root_offset), b"\x00" * (secPerClus * bytesPerSec))
		disk.flush()

		return True

	def _get_packed_table(self) -> bytes:
		return struct.pack("<" + "I" * len(self.table), *self.table)

	def _pre_update_hook(self) -> None:
		if self.fsInfo.is_valid():
			if isinstance(self.header_extended, types.FAT32ExtendedHeader):
				self.disk.write(
					self.lba(self.header_extended.FSInfo), self.fsInfo.to_bytes()
				)

	def get_eof(self) -> int:
		return 0x0FFFFFFF

	def is_eof(self, cluster: int) -> bool:
		return (cluster & 0x0FFFFFFF) >= 0x0FFFFFF8

	def next_cluster(self, current: int) -> int:
		if 0 <= current < len(self.table):
			return self.table[current] & 0x0FFFFFFF
		return 0x0FFFFFFF

	def set_clus(self, cluster: int, value: int):
		if 0 <= cluster < len(self.table):
			self.table[cluster] = (self.table[cluster] & 0xF0000000) | (
				value & 0x0FFFFFFF
			)

	def free_cluster(self) -> int:
		start = (
			self.fsInfo.nextFreeCluster
			if (3 <= self.fsInfo.nextFreeCluster < self.totalClusters)
			else 3
		)
		for c in range(start, self.totalClusters):
			if (self.table[c] & 0x0FFFFFFF) == consts.UNUSED:
				return c
		for c in range(3, start):
			if (self.table[c] & 0x0FFFFFFF) == consts.UNUSED:
				return c
		return 0x0FFFFFFF

	def append_cluster(self, cluster: int) -> int:
		found = super().append_cluster(cluster)
		if found != -1:
			if self.fsInfo.nextFreeCluster != 0xFFFFFFFF:
				self.fsInfo.nextFreeCluster = found + 1
			if (
				self.fsInfo.freeClusterCount != 0xFFFFFFFF
				and self.fsInfo.freeClusterCount > 0
			):
				self.fsInfo.freeClusterCount -= 1
		return found

	def free_chain(self, start: int) -> int:
		count = super().free_chain(start)
		if self.fsInfo.freeClusterCount != 0xFFFFFFFF:
			self.fsInfo.freeClusterCount += count
		if self.fsInfo.nextFreeCluster != 0xFFFFFFFF:
			self.fsInfo.nextFreeCluster = start
		return count


class FAT16(FAT):
	@staticmethod
	def mkfs(disk: Disk, partition: int, start_lba: int, end_lba: int) -> bool:
		start_lba, size_in_lba = FAT._prepare_partition(
			disk, partition, start_lba, end_lba, min_size=64, mbr_type=0x06
		)

		bytesPerSec = 512
		rsvdSecCnt = 1
		numFATs = 2
		rootEntCnt = 512

		if size_in_lba < 32680:
			secPerClus = 2
		elif size_in_lba < 262144:
			secPerClus = 4
		elif size_in_lba < 524288:
			secPerClus = 8
		else:
			secPerClus = 16

		rootDirSectors = ((rootEntCnt * 32) + (bytesPerSec - 1)) // bytesPerSec
		tmpVal1 = size_in_lba - (rsvdSecCnt + rootDirSectors)
		tmpVal2 = (256 * secPerClus) + numFATs
		fatSz16 = (tmpVal1 + (tmpVal2 - 1)) // tmpVal2

		hboot = types.FATBootHeader(
			jmpBoot=b"\xEB\x3C\x90",
			OEMName=b"MSWIN4.1",
			bytesPerSec=bytesPerSec,
			secPerClus=secPerClus,
			rsvdSecCnt=rsvdSecCnt,
			numFATs=numFATs,
			rootEntCnt=rootEntCnt,
			totSec16=size_in_lba if size_in_lba < 65536 else 0,
			mediaType=0xF8,
			FATSz16=fatSz16,
			secPerTrk=63,
			numHeads=16,
			hiddSec=start_lba,
			totSec32=size_in_lba if size_in_lba >= 65536 else 0,
		)

		hextended = types.FAT16ExtendedHeader(
			FATSz16=fatSz16,
			drvNum=0x80,
			reserved1=0,
			bootSig=0x29,
			volID=0xCAFEBAB1,
			volLab=b"NOVA    VOL",
			filSysType=b"FAT16   ",
		)

		fatStartSector = hboot.rsvdSecCnt
		table = bytearray(fatSz16 * bytesPerSec)
		table[0:4] = b"\xF8\xFF\xFF\xFF"

		def lba(sec):
			return start_lba + sec

		boot_sector = bytearray(512)
		boot_sector[0:62] = hboot.to_bytes() + hextended.to_bytes()
		boot_sector[510:512] = b"\x55\xAA"

		disk.write(lba(0), boot_sector)
		disk.write(lba(fatStartSector), table)
		disk.write(lba(fatStartSector + fatSz16), table)

		rootDirStartSector = fatStartSector + (numFATs * fatSz16)
		disk.write(
			lba(rootDirStartSector), b"\x00" * (rootDirSectors * bytesPerSec)
		)
		disk.flush()

		return True

	def _get_packed_table(self) -> bytes:
		return struct.pack("<" + "H" * len(self.table), *self.table)

	def get_eof(self) -> int:
		return 0xFFFF

	def is_eof(self, cluster: int) -> bool:
		return (cluster & 0xFFFF) >= 0xFFF8

	def next_cluster(self, current: int) -> int:
		if 0 <= current < len(self.table):
			return self.table[current] & 0xFFFF
		return 0xFFFF

	def set_clus(self, cluster: int, value: int):
		if 0 <= cluster < len(self.table):
			self.table[cluster] = value & 0xFFFF


class FAT12(FAT):
	@staticmethod
	def mkfs(disk: Disk, partition: int, start_lba: int, end_lba: int) -> bool:
		start_lba, size_in_lba = FAT._prepare_partition(
			disk, partition, start_lba, end_lba, min_size=16, mbr_type=0x01
		)

		bytesPerSec = 512
		rsvdSecCnt = 1
		numFATs = 2
		rootEntCnt = 224

		if size_in_lba < 2048:
			secPerClus = 1
		elif size_in_lba < 4096:
			secPerClus = 2
		elif size_in_lba < 8192:
			secPerClus = 4
		else:
			secPerClus = 8

		rootDirSectors = ((rootEntCnt * 32) + (bytesPerSec - 1)) // bytesPerSec
		tmpVal1 = size_in_lba - (rsvdSecCnt + rootDirSectors)
		tmpVal2 = ((256 * secPerClus) + numFATs) * 3 // 4
		fatSz16 = (tmpVal1 + (tmpVal2 - 1)) // tmpVal2

		hboot = types.FATBootHeader(
			jmpBoot=b"\xEB\x3C\x90",
			OEMName=b"MSWIN4.1",
			bytesPerSec=bytesPerSec,
			secPerClus=secPerClus,
			rsvdSecCnt=rsvdSecCnt,
			numFATs=numFATs,
			rootEntCnt=rootEntCnt,
			totSec16=size_in_lba if size_in_lba < 65536 else 0,
			mediaType=0xF8,
			FATSz16=fatSz16,
			secPerTrk=63,
			numHeads=16,
			hiddSec=size_in_lba,
			totSec32=0,
		)

		hextended = types.FAT12ExtendedHeader(
			FATSz16=fatSz16,
			drvNum=0x80,
			reserved1=0,
			bootSig=0x29,
			volID=0xCAFEBAB1,
			volLab=b"NOVA    VOL",
			filSysType=b"FAT12   ",
		)

		fatStartSector = hboot.rsvdSecCnt
		table = bytearray(fatSz16 * bytesPerSec)
		table[0:3] = b"\xF8\xFF\xFF"

		def lba(sec):
			return start_lba + sec

		boot_sector = bytearray(512)
		boot_sector[0:62] = hboot.to_bytes() + hextended.to_bytes()
		boot_sector[510:512] = b"\x55\xAA"

		disk.write(lba(0), boot_sector)
		disk.write(lba(fatStartSector), table)
		disk.write(lba(fatStartSector + fatSz16), table)

		rootDirStartSector = fatStartSector + (numFATs * fatSz16)
		disk.write(
			lba(rootDirStartSector), b"\x00" * (rootDirSectors * bytesPerSec)
		)
		disk.flush()

		return True

	def _get_packed_table(self) -> bytes:
		return bytes(self.table)

	def get_eof(self) -> int:
		return 0x0FFF

	def is_eof(self, cluster: int) -> bool:
		return (cluster & 0x0FFF) >= 0x0FF8

	def next_cluster(self, current: int) -> int:
		offset = (current * 3) // 2
		if offset + 1 >= len(self.table):
			return 0x0FFF

		b0 = self.table[offset]
		b1 = self.table[offset + 1]

		if current & 1:
			next_clus = (b0 >> 4) | (b1 << 4)
		else:
			next_clus = b0 | ((b1 & 0x0F) << 8)

		return next_clus & 0x0FFF

	def set_clus(self, cluster: int, value: int):
		offset = (cluster * 3) // 2
		if offset + 1 >= len(self.table):
			return

		value &= 0x0FFF

		if cluster & 1:
			self.table[offset] = (self.table[offset] & 0x0F) | (
				(value & 0x0F) << 4
			)
			self.table[offset + 1] = (value >> 4) & 0xFF
		else:
			self.table[offset] = value & 0xFF
			self.table[offset + 1] = (self.table[offset + 1] & 0xF0) | (
				(value >> 8) & 0x0F
			)