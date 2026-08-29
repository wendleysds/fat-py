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

from dataclasses import dataclass, field
from typing import List, Union
import io
import struct
import uuid
import zlib

@dataclass
class GPTPartitionEntry:
	type_guid: bytes
	unique_guid: bytes
	start_lba: int
	end_lba: int
	attributes: int
	name_raw: bytes

	STRUCT_FORMAT = "<16s16sQQQ72s"
	SIZE = 128

	@classmethod
	def from_bytes(cls, data: bytes) -> "GPTPartitionEntry":
		unpacked = struct.unpack(cls.STRUCT_FORMAT, data[: cls.SIZE])
		return cls(*unpacked)

	def to_bytes(self) -> bytes:
		return struct.pack(
			self.STRUCT_FORMAT,
			self.type_guid,
			self.unique_guid,
			self.start_lba,
			self.end_lba,
			self.attributes,
			self.name_raw,
		)

	@property
	def name(self) -> str:
		return self.name_raw.decode("utf-16le").rstrip("\x00")

	@property
	def type_guid_str(self) -> str:
		return str(uuid.UUID(bytes_le=self.type_guid))


@dataclass
class GPTHeader:
	signature: bytes
	revision: int
	header_size: int
	header_crc32: int
	reserved: int
	current_lba: int
	backup_lba: int
	first_usable_lba: int
	last_usable_lba: int
	disk_guid: bytes
	partition_entry_lba: int
	num_partition_entries: int
	size_partition_entry: int
	partition_array_crc32: int

	STRUCT_FORMAT = "<8sIIIIQQQQ16sQIII"
	SIZE = 92

	@classmethod
	def from_bytes(cls, data: bytes) -> "GPTHeader":
		unpacked = struct.unpack(cls.STRUCT_FORMAT, data[: cls.SIZE])
		return cls(*unpacked)

	def to_bytes(self) -> bytes:
		return struct.pack(
			self.STRUCT_FORMAT,
			self.signature,
			self.revision,
			self.header_size,
			self.header_crc32,
			self.reserved,
			self.current_lba,
			self.backup_lba,
			self.first_usable_lba,
			self.last_usable_lba,
			self.disk_guid,
			self.partition_entry_lba,
			self.num_partition_entries,
			self.size_partition_entry,
			self.partition_array_crc32,
		)


@dataclass
class GPT:
	header: GPTHeader
	entries: List[GPTPartitionEntry] = field(default_factory=list)

	@classmethod
	def from_bytes(
		cls, header_bytes: bytes, entries_bytes: bytes
	) -> "GPT":
		header = GPTHeader.from_bytes(header_bytes)
		entries = []
		entry_size = header.size_partition_entry

		for i in range(header.num_partition_entries):
			offset = i * entry_size
			entry_data = entries_bytes[offset : offset + entry_size]
			if len(entry_data) < entry_size:
				break

			entry = GPTPartitionEntry.from_bytes(entry_data)
			if entry.type_guid != b"\x00" * 16:
				entries.append(entry)

		return cls(header=header, entries=entries)

@dataclass
class MBRPartitionEntry:
	bootInd: int
	startHead: int
	startSec: int
	startCyl: int
	partType: int
	endHead: int
	endSec: int
	endCyl: int
	startLBA: int
	sizeInLBA: int

	STRUCT_FORMAT = "<BBBBBBBBII"

	@classmethod
	def from_bytes(cls, data: bytes) -> "MBRPartitionEntry":
		unpacked = struct.unpack(cls.STRUCT_FORMAT, data[: struct.calcsize(cls.STRUCT_FORMAT)])
		return cls(*unpacked)

	def to_bytes(self) -> bytes:
		return struct.pack(
			self.STRUCT_FORMAT,
			self.bootInd,
			self.startHead,
			self.startSec,
			self.startCyl,
			self.partType,
			self.endHead,
			self.endSec,
			self.endCyl,
			self.startLBA,
			self.sizeInLBA,
		)

	@property
	def is_empty(self) -> bool:
		return self.partType == 0 and self.sizeInLBA == 0


@dataclass
class MBR:
	bootstrap_code: bytes = field(default_factory=lambda: b"\x00" * 446)
	entries: List[MBRPartitionEntry] = field(default_factory=list)
	boot_signature: bytes = b"\x55\xaa"

	SECTOR_SIZE = 512
	PARTITION_TABLE_OFFSET = 446
	NUM_ENTRIES = 4
	ENTRY_SIZE = 16

	@classmethod
	def from_bytes(cls, data: bytes) -> "MBR":
		if len(data) < cls.SECTOR_SIZE:
			raise ValueError(f"Os dados do MBR devem ter no mínimo {cls.SECTOR_SIZE} bytes.")

		bootstrap_code = data[: cls.PARTITION_TABLE_OFFSET]
		entries = []

		for i in range(cls.NUM_ENTRIES):
			offset = cls.PARTITION_TABLE_OFFSET + (i * cls.ENTRY_SIZE)
			entry_bytes = data[offset : offset + cls.ENTRY_SIZE]
			entry = MBRPartitionEntry.from_bytes(entry_bytes)
			
			if not entry.is_empty:
				entries.append(entry)

		boot_signature = data[510:512]

		return cls(
			bootstrap_code=bootstrap_code,
			entries=entries,
			boot_signature=boot_signature,
		)

	def to_bytes(self) -> bytes:
		bootstrap = self.bootstrap_code.ljust(446, b"\x00")[:446]
		entries_bytes = bytearray()

		for i in range(self.NUM_ENTRIES):
			if i < len(self.entries):
				entries_bytes.extend(self.entries[i].to_bytes())
			else:
				entries_bytes.extend(b"\x00" * self.ENTRY_SIZE)

		return bootstrap + bytes(entries_bytes) + self.boot_signature

	@property
	def is_valid(self) -> bool:
		return self.boot_signature == b"\x55\xaa"

class Disk:
	partitions: Union[MBR, GPT]

	def __init__(self, file: io.BufferedRandom, sector_size: int = 512):
		self.file = file
		self.sector_size = sector_size
		self._load()

	def _load(self) -> None:
		sector_0 = self.read(0, self.sector_size)

		try:
			mbr = MBR.from_bytes(sector_0)
		except ValueError:
			self.partitions = MBR()
			return

		is_gpt = False
		if mbr.is_valid:
			for entry in mbr.entries:
				if entry.partType == 0xEE:
					is_gpt = True
					break

		if not is_gpt:
			lba_1 = self.read(1, self.sector_size)
			if lba_1[:8] == b"EFI PART":
				is_gpt = True

		if is_gpt:
			header_bytes = self.read(1, self.sector_size)
			header = GPTHeader.from_bytes(header_bytes)

			entries_bytes_size = header.num_partition_entries * header.size_partition_entry
			entries_bytes = self.read(header.partition_entry_lba, entries_bytes_size)

			self.partitions = GPT.from_bytes(header_bytes, entries_bytes)
		else:
			self.partitions = mbr

	def save(self) -> None:
		if isinstance(self.partitions, MBR):
			self.write(0, self.partitions.to_bytes())
		elif isinstance(self.partitions, GPT):
			header = self.partitions.header

			entries_buf = bytearray()
			for i in range(header.num_partition_entries):
				if i < len(self.partitions.entries):
					entries_buf.extend(self.partitions.entries[i].to_bytes())
				else:
					entries_buf.extend(b"\x00" * header.size_partition_entry)

			header.partition_array_crc32 = zlib.crc32(entries_buf) & 0xFFFFFFFF
			header.header_crc32 = 0
			hdr_bytes = header.to_bytes()
			header.header_crc32 = zlib.crc32(hdr_bytes[:header.header_size]) & 0xFFFFFFFF

			self.write(header.current_lba, header.to_bytes().ljust(self.sector_size, b"\x00"))
			self.write(header.partition_entry_lba, entries_buf)

		self.flush()

	def partition_add(
		self,
		startLBA: int,
		sizeInLBA: int,
		bootable: bool = False,
		uuid_str: str | None = None,
	) -> int:
		if isinstance(self.partitions, MBR):
			if len(self.partitions.entries) >= MBR.NUM_ENTRIES:
				raise ValueError("Limite de 4 partições primárias no MBR atingido.")

			entry = MBRPartitionEntry(
				bootInd=0x80 if bootable else 0x00,
				startHead=0,
				startSec=0,
				startCyl=0,
				partType=0x83,
				endHead=0,
				endSec=0,
				endCyl=0,
				startLBA=startLBA,
				sizeInLBA=sizeInLBA,
			)
			self.partitions.entries.append(entry)

		elif isinstance(self.partitions, GPT):
			if len(self.partitions.entries) >= self.partitions.header.num_partition_entries:
				raise ValueError("Limite de entradas GPT atingido.")

			default_type_guid = "EBD0A0A2-B9E5-4433-87C0-68B6B72699C7"
			type_guid_bytes = uuid.UUID(uuid_str or default_type_guid).bytes_le
			unique_guid_bytes = uuid.uuid4().bytes_le

			entry = GPTPartitionEntry(
				type_guid=type_guid_bytes,
				unique_guid=unique_guid_bytes,
				start_lba=startLBA,
				end_lba=startLBA + sizeInLBA - 1,
				attributes=0x4 if bootable else 0,
				name_raw="Partition".encode("utf-16le").ljust(72, b"\x00"),
			)
			self.partitions.entries.append(entry)

		self.save()
		return len(self.partitions.entries) - 1

	def partition_update(
		self,
		index: int,
		startLBA: int,
		sizeInLBA: int,
		bootable: bool = False,
		uuid_str: str | None = None,
	) -> bool:
		if index < 0 or index >= len(self.partitions.entries):
			return False

		if isinstance(self.partitions, MBR):
			entry = self.partitions.entries[index]
			entry.startLBA = startLBA
			entry.sizeInLBA = sizeInLBA
			entry.bootInd = 0x80 if bootable else 0x00

		elif isinstance(self.partitions, GPT):
			entry = self.partitions.entries[index]
			entry.start_lba = startLBA
			entry.end_lba = startLBA + sizeInLBA - 1

			if bootable:
				entry.attributes |= 0x4
			else:
				entry.attributes &= ~0x4

			if uuid_str:
				entry.type_guid = uuid.UUID(uuid_str).bytes_le

		self.save()
		return True

	def partition_remove(self, index: int) -> bool:
		if index < 0 or index >= len(self.partitions.entries):
			return False

		self.partitions.entries.pop(index)
		self.save()
		return True
	
	def read_at(self, byte_offset: int, count: int) -> bytes:
		self.file.seek(byte_offset)
		return self.file.read(count)

	def write_at(self, byte_offset: int, data: bytes) -> int:
		self.file.seek(byte_offset)
		return self.file.write(data)

	def read_lba(self, lba: int, count_bytes: int) -> bytes:
		return self.read_at(lba * self.sector_size, count_bytes)

	def write_lba(self, lba: int, data: bytes) -> int:
		return self.write_at(lba * self.sector_size, data)

	def read(self, lba: int, count: int) -> bytes:
		return self.read_lba(lba, count)

	def write(self, lba: int, data: bytes) -> int:
		return self.write_lba(lba, data)
	
	def flush(self):
		self.file.flush()
