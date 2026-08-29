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

from dataclasses import dataclass
from fat.partition import Disk, MBRPartitionEntry
import fat.consts as consts
from typing import Union
from array import array
import struct

@dataclass
class FATBootHeader:
	jmpBoot: bytes  # 3 bytes
	OEMName: bytes  # 8 bytes
	bytesPerSec: int
	secPerClus: int
	rsvdSecCnt: int
	numFATs: int
	rootEntCnt: int
	totSec16: int
	mediaType: int
	FATSz16: int
	secPerTrk: int
	numHeads: int
	hiddSec: int
	totSec32: int

	STRUCT_FORMAT = "<3s8sHBHBHHBHHHII"

	@classmethod
	def from_bytes(cls, data: bytes) -> "FATBootHeader":
		unpacked = struct.unpack(cls.STRUCT_FORMAT, data[:struct.calcsize(cls.STRUCT_FORMAT)])
		return cls(*unpacked)

	def to_bytes(self) -> bytes:
		return struct.pack(
			self.STRUCT_FORMAT,
			self.jmpBoot,
			self.OEMName,
			self.bytesPerSec,
			self.secPerClus,
			self.rsvdSecCnt,
			self.numFATs,
			self.rootEntCnt,
			self.totSec16,
			self.mediaType,
			self.FATSz16,
			self.secPerTrk,
			self.numHeads,
			self.hiddSec,
			self.totSec32
		)

@dataclass
class FAT16ExtendedHeader:
	FATSz16: int
	drvNum: int
	reserved1: int
	bootSig: int
	volID: int
	volLab: bytes  # 11 bytes
	filSysType: bytes  # 8 bytes

	STRUCT_FORMAT = "<HBBB I 11s8s"

	@classmethod
	def from_bytes(cls, data: bytes) -> "FAT16ExtendedHeader":
		unpacked = struct.unpack(cls.STRUCT_FORMAT, data[:struct.calcsize(cls.STRUCT_FORMAT)])
		return cls(*unpacked)

	def to_bytes(self) -> bytes:
		return struct.pack(
			self.STRUCT_FORMAT,
			self.FATSz16,
			self.drvNum,
			self.reserved1,
			self.bootSig,
			self.volID,
			self.volLab,
			self.filSysType
		)

@dataclass
class FAT12ExtendedHeader:
	FATSz16: int
	drvNum: int
	reserved1: int
	bootSig: int
	volID: int
	volLab: bytes  # 11 bytes
	filSysType: bytes  # 8 bytes

	STRUCT_FORMAT = "<HBBB I 11s8s"

	@classmethod
	def from_bytes(cls, data: bytes) -> "FAT12ExtendedHeader":
		unpacked = struct.unpack(cls.STRUCT_FORMAT, data[:struct.calcsize(cls.STRUCT_FORMAT)])
		return cls(*unpacked)

	def to_bytes(self) -> bytes:
		return struct.pack(
			self.STRUCT_FORMAT,
			self.FATSz16,
			self.drvNum,
			self.reserved1,
			self.bootSig,
			self.volID,
			self.volLab,
			self.filSysType
		)

@dataclass
class FAT32ExtendedHeader:
	FATSz32: int
	extFlags: int
	FSVer: int
	rootClus: int
	FSInfo: int
	BkBootSec: int
	reserved: bytes  # 12 bytes
	drvNum: int
	reserved1: int
	bootSig: int
	volID: int
	volLab: bytes  # 11 bytes
	filSysType: bytes  # 8 bytes

	STRUCT_FORMAT = "<IHHIHH12sBBB I 11s8s"

	@classmethod
	def from_bytes(cls, data: bytes) -> "FAT32ExtendedHeader":
		unpacked = struct.unpack(cls.STRUCT_FORMAT, data[:struct.calcsize(cls.STRUCT_FORMAT)])
		return cls(*unpacked)

	def to_bytes(self) -> bytes:
		return struct.pack(
			self.STRUCT_FORMAT,
			self.FATSz32,
			self.extFlags,
			self.FSVer,
			self.rootClus,
			self.FSInfo,
			self.BkBootSec,
			self.reserved,
			self.drvNum,
			self.reserved1,
			self.bootSig,
			self.volID,
			self.volLab,
			self.filSysType
		)

@dataclass
class FATDirectoryEntry:
	name: bytes  # 11 bytes
	attr: int
	NTRes: int
	crtTimeTenth: int
	crtTime: int
	crtDate: int
	lstAccDate: int
	fstClusHI: int
	wrtTime: int
	wrtDate: int
	fstClusLO: int
	fileSize: int

	STRUCT_FORMAT = "<11sBBBHHHHHHHI"

	@classmethod
	def from_bytes(cls, data: bytes) -> "FATDirectoryEntry":
		unpacked = struct.unpack(cls.STRUCT_FORMAT, data[:struct.calcsize(cls.STRUCT_FORMAT)])
		return cls(*unpacked)

	def to_bytes(self) -> bytes:
		return struct.pack(
			self.STRUCT_FORMAT,
			self.name,
			self.attr,
			self.NTRes,
			self.crtTimeTenth,
			self.crtTime,
			self.crtDate,
			self.lstAccDate,
			self.fstClusHI,
			self.wrtTime,
			self.wrtDate,
			self.fstClusLO,
			self.fileSize
		)

	def get_cluster(self) -> int:
		return (self.fstClusHI << 16) | self.fstClusLO

	def set_cluster(self, cluster: int) -> None:
		self.fstClusHI = (cluster >> 16) & 0xFFFF
		self.fstClusLO = cluster & 0xFFFF

	def is_empty(self) -> bool:
		return self.name[0] == 0x00

	def is_deleted(self) -> bool:
		return self.name[0] == 0xE5

	def is_free_slot(self) -> bool:
		return self.is_empty() or self.is_deleted()

	def is_lfn(self) -> bool:
		return (self.attr & consts.LONG_NAME_MASK) == consts.LONG_NAME

	def is_directory(self) -> bool:
		return bool(self.attr & consts.DIRECTORY)

	def __str__(self):
		name_str = self.name.decode('latin1', errors='ignore')
		attr_str = []
		if self.attr & consts.READ_ONLY: attr_str.append("RONLY")
		if self.attr & consts.HIDDEN: attr_str.append("Hidden")
		if self.attr & consts.SYSTEM: attr_str.append("System")
		if self.attr & consts.VOLUME: attr_str.append("Volume")
		if self.attr & consts.DIRECTORY: attr_str.append("Directory")
		if self.attr & consts.ARCHIVE: attr_str.append("Archive")
		
		attrs = " | ".join(attr_str) if attr_str else "None"
		clus = self.get_cluster()
		return f"Entry(name='{name_str}', attr={attrs}, cluster={clus}, size={self.fileSize})"

@dataclass
class FAT32FSInfo:
	leadSignature: int       # 0x41615252
	reserved1: bytes         # 480 bytes
	structSignature: int     # 0x61417272
	freeClusterCount: int    # 0xFFFFFFFF if unknown
	nextFreeCluster: int     # 0xFFFFFFFF if unknown
	reserved2: bytes         # 12 bytes
	trailSignature: int      # 0xAA550000

	STRUCT_FORMAT = "<I480sIII12sI"

	@classmethod
	def from_bytes(cls, data: bytes) -> "FAT32FSInfo":
		unpacked = struct.unpack(cls.STRUCT_FORMAT, data[:struct.calcsize(cls.STRUCT_FORMAT)])
		return cls(*unpacked)

	def to_bytes(self) -> bytes:
		return struct.pack(
			self.STRUCT_FORMAT,
			self.leadSignature,
			self.reserved1,
			self.structSignature,
			self.freeClusterCount,
			self.nextFreeCluster,
			self.reserved2,
			self.trailSignature
		)

	def is_valid(self) -> bool:
		return (
			self.leadSignature == 0x41615252 and
			self.structSignature == 0x61417272 and
			self.trailSignature == 0xAA550000
		)

	@classmethod
	def create_default(cls, free_count: int = 0xFFFFFFFF, next_free: int = 3) -> "FAT32FSInfo":
		return cls(
			leadSignature=0x41615252,
			reserved1=b"\x00" * 480,
			structSignature=0x61417272,
			freeClusterCount=free_count,
			nextFreeCluster=next_free,
			reserved2=b"\x00" * 12,
			trailSignature=0xAA550000
		)

class FAT:
	def __init__(
		self,
		header_boot: FATBootHeader,
		header_extended: Union [
			FAT16ExtendedHeader,
			FAT12ExtendedHeader,
			FAT32ExtendedHeader,
		],
		disk: Disk,
		start_lba: int,
		table: Union[array, bytearray],
		totalClusters: int,
		firstDataSector: int,
		clusterSize: int,
	):
		self.header_boot = header_boot
		self.header_extended = header_extended
		self.disk = disk
		self.start_lba = start_lba
		self.table = table
		self.totalClusters = totalClusters
		self.firstDataSector = firstDataSector
		self.clusterSize = clusterSize

	def lba(self, relative_sector: int) -> int:
		return self.start_lba + relative_sector

	def lba_to_offset(self, lba: int) -> int:
		return self.lba(lba) * self.header_boot.bytesPerSec

	def cluster_to_lba(self, cluster: int) -> int:
		return self.firstDataSector + (
			(cluster - 2) * self.header_boot.secPerClus
		)

	@classmethod
	def _prepare_partition(
		cls,
		disk: Disk,
		partition: int,
		start_lba: int,
		end_lba: int,
		min_size: int,
		mbr_type: int,
	) -> tuple[int, int]:
		part_idx = (partition - 1) if partition >= 1 else 0
		part_size = end_lba - start_lba

		if part_size < min_size:
			raise ValueError(
				f"Tamanho de partição muito pequeno para {cls.__name__}"
			)

		if part_idx < len(disk.partitions.entries):
			disk.partition_update(
				index=part_idx, startLBA=start_lba, sizeInLBA=part_size
			)
		else:
			while len(disk.partitions.entries) <= part_idx:
				disk.partition_add(startLBA=start_lba, sizeInLBA=part_size)

		entry = disk.partitions.entries[part_idx]

		if isinstance(entry, MBRPartitionEntry):
			start_lba = entry.startLBA
			size_in_lba = entry.sizeInLBA
			entry.partType = mbr_type
			disk.save()
		else:
			start_lba = entry.start_lba
			size_in_lba = (entry.end_lba - entry.start_lba) + 1

		return start_lba, size_in_lba

	def fat_size_sectors(self) -> int:
		return getattr(self.header_boot, "FATSz16", 0) or getattr(
			self.header_extended, "FATSz32", 0
		)

	def _get_packed_table(self) -> bytes:
		raise NotImplementedError

	def _pre_update_hook(self) -> None:
		pass

	def update(self) -> None:
		self._pre_update_hook()
		fat_start = self.header_boot.rsvdSecCnt
		fat_size = self.fat_size_sectors()
		packed_table = self._get_packed_table()

		for i in range(self.header_boot.numFATs):
			self.disk.write(self.lba(fat_start + i * fat_size), packed_table)

		self.disk.flush()

	def free_cluster(self) -> int:
		for cluster in range(2, self.totalClusters):
			if self.next_cluster(cluster) == consts.UNUSED:
				return cluster
		return self.get_eof()

	def append_cluster(self, cluster: int) -> int:
		found = self.free_cluster()
		if found == -1 or self.is_eof(found):
			return -1

		self.set_clus(cluster, found)
		self.set_clus(found, self.get_eof())
		return found

	def free_chain(self, start: int) -> int:
		count = 0
		cur = start

		while 2 <= cur < self.totalClusters and not self.is_eof(cur):
			next_clus = self.next_cluster(cur)
			self.set_clus(cur, consts.UNUSED)
			cur = next_clus
			count += 1

		return count

	def is_eof(self, cluster: int) -> bool:
		raise NotImplementedError

	def get_eof(self) -> int:
		raise NotImplementedError

	def next_cluster(self, current: int) -> int:
		raise NotImplementedError

	def set_clus(self, cluster: int, value: int) -> None:
		raise NotImplementedError