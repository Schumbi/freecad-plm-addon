import json
import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from xml.etree import ElementTree
from zipfile import ZipFile

from freecad_plm_addon.errors import WorkspaceError
from freecad_plm_addon.workspace import (
    archive_import_source_dir,
    archived_import_dir,
    build_checkout_metadata,
    build_project_import_zip,
    changed_manifest_files,
    collect_project_fcstd_files,
    checkout_dir,
    download_manifest_files,
    delete_checkout_manifest_file,
    ensure_checkout_metadata,
    ensure_checkout_manifest_files,
    fcstd_technical_hashes,
    merge_checkout_metadata,
    prune_readonly_cache,
    read_manifest,
    readonly_revision_dir,
    removable_manifest_files,
    root_file_path,
    safe_join,
    safe_download_filename,
    server_slug,
    set_fcstd_plm_revision,
    set_document_string_property,
    sha256_file,
    technically_changed_manifest_files,
    touch_directory,
    update_changed_files_plm_revisions,
    write_checkout_metadata,
    write_manifest,
)


class WorkspaceTests(unittest.TestCase):
    def test_removable_manifest_files_excludes_root(self):
        manifest = {
            "files": [
                {"path": "Assembly.FCStd", "is_root": True},
                {"path": "Box.FCStd", "is_root": False},
            ]
        }

        self.assertEqual(
            removable_manifest_files(manifest),
            [{"path": "Box.FCStd", "is_root": False}],
        )

    def test_delete_checkout_manifest_file_removes_file_and_empty_parent(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "files" / "parts" / "Box.FCStd"
            target.parent.mkdir(parents=True)
            target.write_bytes(b"content")

            removed = delete_checkout_manifest_file(tmp, "parts/Box.FCStd")

            self.assertEqual(removed, target)
            self.assertFalse(target.exists())
            self.assertFalse(target.parent.exists())

    def make_fcstd(self, path, revision_code="R0001"):
        document_xml = f"""<?xml version='1.0' encoding='utf-8'?>
<Document>
  <Properties Count="1">
    <Property name="PLMRevision" type="App::PropertyString">
      <String value="{revision_code}" />
    </Property>
  </Properties>
</Document>
""".encode("utf-8")
        with ZipFile(path, "w") as archive:
            archive.writestr("Document.xml", document_xml)
            archive.writestr("PartShape.brp", b"shape")
            archive.writestr("GuiDocument.xml", b"<GuiDocument />")

    def read_fcstd_plm_revision(self, path):
        with ZipFile(path) as archive:
            document_xml = archive.read("Document.xml")
        root = ElementTree.fromstring(document_xml)
        node = root.find("./Properties/Property[@name='PLMRevision']/String")
        return node.attrib["value"]

    def replace_fcstd_member(self, path, member_name, content):
        with ZipFile(path) as archive:
            entries = {
                info.filename: archive.read(info.filename)
                for info in archive.infolist()
                if info.filename != member_name
            }
        entries[member_name] = content
        with ZipFile(path, "w") as archive:
            for name, data in entries.items():
                archive.writestr(name, data)

    def set_fcstd_string_property(self, path, name, value):
        with ZipFile(path) as archive:
            document_xml = archive.read("Document.xml")
        updated = set_document_string_property(document_xml, name, value)
        self.replace_fcstd_member(path, "Document.xml", updated)

    def mutate_fcstd_document_xml(self, path, mutate):
        with ZipFile(path) as archive:
            root = ElementTree.fromstring(archive.read("Document.xml"))
        mutate(root)
        self.replace_fcstd_member(
            path,
            "Document.xml",
            ElementTree.tostring(root, encoding="utf-8", xml_declaration=True),
        )

    def test_safe_join_rejects_absolute_paths(self):
        with self.assertRaises(WorkspaceError):
            safe_join("/tmp/root", "/etc/passwd")

    def test_safe_join_rejects_parent_paths(self):
        with self.assertRaises(WorkspaceError):
            safe_join("/tmp/root", "../x.FCStd")

    def test_server_slug(self):
        self.assertEqual(server_slug("https://plm.lan.schumbi.de"), "plm-lan-schumbi-de")

    def test_manifest_roundtrip_and_root_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest = {
                "files": [
                    {"path": "A.FCStd", "is_root": True},
                    {"path": "sub/B.FCStd", "is_root": False},
                ]
            }
            write_manifest(tmp, manifest)
            self.assertEqual(read_manifest(tmp), manifest)
            self.assertEqual(root_file_path(manifest, tmp), Path(tmp) / "files" / "A.FCStd")

    def test_sha256_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "data.txt"
            path.write_text("abc", encoding="utf-8")
            self.assertEqual(
                sha256_file(path),
                "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
            )

    def test_collect_project_fcstd_files_returns_supported_cad_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_fcstd(root / "Root.FCStd")
            (root / "parts").mkdir()
            self.make_fcstd(root / "parts" / "Box.FCStd")
            (root / "parts" / "Bracket.step").write_text("step", encoding="utf-8")
            (root / "Mesh.stl").write_text("stl", encoding="utf-8")
            (root / "notes.txt").write_text("ignore", encoding="utf-8")

            files = collect_project_fcstd_files(root)

            self.assertEqual(
                [relative_path for relative_path, _local_path in files],
                ["Mesh.stl", "Root.FCStd", "parts/Box.FCStd", "parts/Bracket.step"],
            )

    def test_collect_project_fcstd_files_requires_supported_cad_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(WorkspaceError):
                collect_project_fcstd_files(tmp)

    def test_build_project_import_zip_keeps_relative_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            root.mkdir()
            self.make_fcstd(root / "Assembly.FCStd")
            (root / "parts").mkdir()
            self.make_fcstd(root / "parts" / "Box.FCStd")
            (root / "parts" / "Vendor.step").write_text("step", encoding="utf-8")
            target = Path(tmp) / "project.zip"

            paths = build_project_import_zip(root, target)

            self.assertEqual(paths, ["Assembly.FCStd", "parts/Box.FCStd", "parts/Vendor.step"])
            with ZipFile(target) as archive:
                self.assertEqual(
                    archive.namelist(),
                    ["Assembly.FCStd", "parts/Box.FCStd", "parts/Vendor.step"],
                )

    def test_archived_import_dir_adds_timestamp_server_and_project(self):
        path = archived_import_dir(
            "/tmp/workspace",
            "https://plm.example",
            "PRJ",
            "/tmp/source-folder",
            now=datetime(2026, 7, 8, 12, 30, 5),
        )

        self.assertEqual(
            path,
            Path("/tmp/workspace/imported/plm-example/PRJ/20260708-123005-source-folder"),
        )

    def test_archive_import_source_dir_moves_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            source.mkdir()
            (source / "part.FCStd").write_text("data", encoding="utf-8")

            target = archive_import_source_dir(
                source,
                root / "workspace",
                "https://plm.example",
                "PRJ",
                now=datetime(2026, 7, 8, 12, 30, 5),
            )

            self.assertFalse(source.exists())
            self.assertEqual(
                target,
                root / "workspace/imported/plm-example/PRJ/20260708-123005-source",
            )
            self.assertEqual((target / "part.FCStd").read_text(encoding="utf-8"), "data")

    def test_archive_import_source_dir_rejects_target_inside_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source"
            source.mkdir()
            with self.assertRaises(WorkspaceError):
                archive_import_source_dir(
                    source,
                    source,
                    "https://plm.example",
                    "PRJ",
                    now=datetime(2026, 7, 8, 12, 30, 5),
                )

    def test_checkout_dir(self):
        path = checkout_dir("~/FreeCAD-PLM", "https://plm.lan.schumbi.de", "PRJ", 17)
        self.assertEqual(path.name, "checkout-17")
        self.assertEqual(path.parent.name, "PRJ")

    def test_readonly_revision_dir(self):
        path = readonly_revision_dir("~/FreeCAD-PLM", "https://plm.lan.schumbi.de", "PRJ", 23)
        self.assertEqual(path.name, "revision-23")
        self.assertEqual(path.parent.name, "readonly")
        self.assertEqual(path.parent.parent.name, "PRJ")

    def test_safe_download_filename_strips_path(self):
        self.assertEqual(safe_download_filename("../part.FCStd"), "part.FCStd")
        self.assertEqual(safe_download_filename("/tmp/part.FCStd"), "part.FCStd")
        self.assertEqual(safe_download_filename(""), "revision.FCStd")

    def make_readonly_revision(self, root, project, revision_id, file_count=1, mtime=1):
        revision_dir = (
            Path(root)
            / "plm-lan-schumbi-de"
            / project
            / "readonly"
            / f"revision-{revision_id}"
        )
        revision_dir.mkdir(parents=True)
        for index in range(file_count):
            (revision_dir / f"part-{index}.FCStd").write_text("data", encoding="utf-8")
        os.utime(revision_dir, (mtime, mtime))
        return revision_dir

    def test_touch_directory_updates_cache_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "revision-1"

            touch_directory(path)

            self.assertTrue(path.is_dir())

    def test_prune_readonly_cache_keeps_five_revisions_per_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            for index in range(7):
                self.make_readonly_revision(tmp, "PRJ", index, mtime=index + 1)

            removed = prune_readonly_cache(
                tmp,
                "https://plm.lan.schumbi.de",
                current_project_code="PRJ",
                current_revision_id=6,
            )

            self.assertEqual(len(removed), 2)
            self.assertFalse((Path(tmp) / "plm-lan-schumbi-de" / "PRJ" / "readonly" / "revision-0").exists())
            self.assertFalse((Path(tmp) / "plm-lan-schumbi-de" / "PRJ" / "readonly" / "revision-1").exists())
            self.assertTrue((Path(tmp) / "plm-lan-schumbi-de" / "PRJ" / "readonly" / "revision-6").exists())

    def test_prune_readonly_cache_keeps_five_projects(self):
        with tempfile.TemporaryDirectory() as tmp:
            for index in range(7):
                self.make_readonly_revision(tmp, f"PRJ{index}", 1, mtime=index + 1)

            removed = prune_readonly_cache(
                tmp,
                "https://plm.lan.schumbi.de",
                current_project_code="PRJ6",
                current_revision_id=1,
            )

            self.assertEqual(len(removed), 2)
            self.assertFalse((Path(tmp) / "plm-lan-schumbi-de" / "PRJ0" / "readonly").exists())
            self.assertFalse((Path(tmp) / "plm-lan-schumbi-de" / "PRJ1" / "readonly").exists())
            self.assertTrue((Path(tmp) / "plm-lan-schumbi-de" / "PRJ6" / "readonly").exists())

    def test_prune_readonly_cache_limits_fcstd_files_by_removing_project_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.make_readonly_revision(tmp, "OLD", 1, file_count=12, mtime=1)
            self.make_readonly_revision(tmp, "MID", 1, file_count=8, mtime=2)
            self.make_readonly_revision(tmp, "CUR", 1, file_count=5, mtime=3)

            removed = prune_readonly_cache(
                tmp,
                "https://plm.lan.schumbi.de",
                current_project_code="CUR",
                current_revision_id=1,
            )

            self.assertEqual(len(removed), 1)
            self.assertFalse((Path(tmp) / "plm-lan-schumbi-de" / "OLD" / "readonly").exists())
            self.assertTrue((Path(tmp) / "plm-lan-schumbi-de" / "MID" / "readonly").exists())
            self.assertTrue((Path(tmp) / "plm-lan-schumbi-de" / "CUR" / "readonly").exists())

    def test_download_manifest_files_chmods_existing_readonly_file(self):
        class FakeClient:
            def download_revision_file(self, _url, target_path, _sha256):
                Path(target_path).write_bytes(b"abc")

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "files" / "part.FCStd"
            path.parent.mkdir(parents=True)
            path.write_bytes(b"old")
            path.chmod(0o444)
            manifest = {
                "files": [
                    {
                        "path": "part.FCStd",
                        "download_url": "https://plm.example/file",
                        "sha256": "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
                    }
                ]
            }

            downloaded = download_manifest_files(FakeClient(), manifest, tmp)

            self.assertEqual(downloaded, [path])
            self.assertEqual(path.read_bytes(), b"abc")

    def test_ensure_checkout_manifest_files_does_not_overwrite_existing_file(self):
        class FakeClient:
            def __init__(self):
                self.calls = 0

            def download_revision_file(self, _url, target_path, _sha256):
                self.calls += 1
                Path(target_path).write_bytes(b"abc")

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "files" / "part.FCStd"
            path.parent.mkdir(parents=True)
            path.write_bytes(b"local changes")
            manifest = {
                "files": [
                    {
                        "path": "part.FCStd",
                        "download_url": "https://plm.example/file",
                        "sha256": "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
                    }
                ]
            }
            client = FakeClient()

            downloaded = ensure_checkout_manifest_files(client, manifest, tmp)

            self.assertEqual(downloaded, [])
            self.assertEqual(client.calls, 0)
            self.assertEqual(path.read_bytes(), b"local changes")

    def test_changed_manifest_files_returns_modified_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "files" / "part.FCStd"
            path.parent.mkdir(parents=True)
            path.write_bytes(b"changed")
            manifest = {
                "files": [
                    {
                        "path": "part.FCStd",
                        "revision_id": 10,
                        "sha256": "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
                        "is_root": True,
                    }
                ]
            }

            changed = changed_manifest_files(manifest, tmp)

            self.assertEqual(len(changed), 1)
            self.assertEqual(changed[0]["path"], "part.FCStd")
            self.assertEqual(changed[0]["local_path"], path)
            self.assertEqual(changed[0]["revision_id"], 10)
            self.assertTrue(changed[0]["is_root"])
            self.assertNotEqual(changed[0]["sha256"], changed[0]["base_sha256"])

    def test_fcstd_technical_hashes_ignore_gui_document(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "part.FCStd"
            self.make_fcstd(path, "R0001")
            before = fcstd_technical_hashes(path)

            self.replace_fcstd_member(path, "GuiDocument.xml", b"<GuiDocument camera='changed' />")

            self.assertEqual(fcstd_technical_hashes(path), before)

    def test_fcstd_technical_hashes_ignore_volatile_document_properties(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "part.FCStd"
            self.make_fcstd(path, "R0001")
            before = fcstd_technical_hashes(path)

            self.set_fcstd_string_property(path, "LastModifiedDate", "2026-07-07T14:04:28+02:00")
            self.set_fcstd_string_property(path, "LastModifiedBy", "ralf")
            set_fcstd_plm_revision(path, "R0002")

            self.assertEqual(fcstd_technical_hashes(path), before)

    def test_fcstd_technical_hashes_ignore_freecad_save_noise_attributes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "part.FCStd"
            self.make_fcstd(path, "R0001")
            before = fcstd_technical_hashes(path)

            def mutate(root):
                root.attrib["Touched"] = "1"
                property_node = root.find("./Properties/Property[@name='PLMRevision']")
                property_node.attrib["status"] = "128"
                property_node.attrib["stamp"] = "2026-07-07T14:27:49+02:00"

            self.mutate_fcstd_document_xml(path, mutate)

            self.assertEqual(fcstd_technical_hashes(path), before)

    def test_fcstd_technical_hashes_ignore_checkout_path_rewrites(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "part.FCStd"
            self.make_fcstd(path, "R0001")

            def add_bom_cell(root):
                object_data = ElementTree.SubElement(root, "ObjectData")
                obj = ElementTree.SubElement(object_data, "Object", {"name": "Bill_of_Materials"})
                properties = ElementTree.SubElement(obj, "Properties", {"Count": "1"})
                prop = ElementTree.SubElement(properties, "Property", {"name": "cells"})
                cells = ElementTree.SubElement(prop, "Cells", {"Count": "1"})
                ElementTree.SubElement(
                    cells,
                    "Cell",
                    {
                        "address": "D2",
                        "content": "'/home/ralf/FreeCAD-PLM/plm-lan-schumbi-de/CB2/checkout-29/files/Box.FCStd",
                    },
                )

            self.mutate_fcstd_document_xml(path, add_bom_cell)
            before = fcstd_technical_hashes(path)

            def rewrite_checkout_path(root):
                cell = root.find("./ObjectData/Object/Properties/Property/Cells/Cell")
                cell.attrib[
                    "content"
                ] = "'/home/ralf/FreeCAD-PLM/plm-lan-schumbi-de/CB2/checkout-30/files/Box.FCStd"

            self.mutate_fcstd_document_xml(path, rewrite_checkout_path)

            self.assertEqual(fcstd_technical_hashes(path), before)

    def test_fcstd_technical_hashes_ignore_tiny_placement_rounding_noise(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "part.FCStd"
            self.make_fcstd(path, "R0001")

            def add_placement(root):
                object_data = ElementTree.SubElement(root, "ObjectData")
                obj = ElementTree.SubElement(object_data, "Object", {"name": "Body"})
                properties = ElementTree.SubElement(obj, "Properties", {"Count": "1"})
                prop = ElementTree.SubElement(properties, "Property", {"name": "Placement"})
                ElementTree.SubElement(
                    prop,
                    "PropertyPlacement",
                    {
                        "Px": "44.4999999999896332",
                        "Py": "-0.0000000000014071",
                        "Pz": "25.6250000000000000",
                    },
                )

            self.mutate_fcstd_document_xml(path, add_placement)
            before = fcstd_technical_hashes(path)

            def rewrite_rounding(root):
                placement = root.find(
                    "./ObjectData/Object/Properties/Property/PropertyPlacement"
                )
                placement.attrib["Px"] = "44.4999999999896332"
                placement.attrib["Py"] = "-0.0000000000014085"
                placement.attrib["Pz"] = "25.6250000000000000"

            self.mutate_fcstd_document_xml(path, rewrite_rounding)

            self.assertEqual(fcstd_technical_hashes(path), before)

    def test_fcstd_technical_hashes_ignore_freecad_build_migration(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "part.FCStd"
            self.make_fcstd(path, "R0001")
            legacy_xml = b"""
                <Document ProgramVersion="1.1R44874 (Git)">
                    <ObjectData>
                        <Object name="Sketch001">
                            <Properties Count="2">
                                <Property name="AttacherEngine" type="App::PropertyEnumeration">
                                    <Integer value="0" CustomEnum="true" />
                                    <CustomEnumList count="4">
                                        <Enum value="Engine 3D" />
                                        <Enum value="Engine Plane" />
                                        <Enum value="Engine Line" />
                                        <Enum value="Engine Point" />
                                    </CustomEnumList>
                                </Property>
                                <Property name="AttacherType" type="App::PropertyString">
                                    <String value="Attacher::AttachEnginePlane" />
                                </Property>
                            </Properties>
                        </Object>
                    </ObjectData>
                </Document>
            """
            self.replace_fcstd_member(path, "Document.xml", legacy_xml)
            before = fcstd_technical_hashes(path)

            def migrate(root):
                root.attrib["ProgramVersion"] = "1.1R44987 (Git)"
                properties = root.find("./ObjectData/Object/Properties")
                properties.find("./Property[@name='AttacherEngine']/Integer").attrib[
                    "value"
                ] = "1"
                fuzzy = ElementTree.SubElement(
                    properties,
                    "Property",
                    {"name": "FuzzyTolerance", "type": "App::PropertyLength"},
                )
                ElementTree.SubElement(fuzzy, "Float", {"value": "-1.0000000000000000"})
                properties.attrib["Count"] = "3"

            self.mutate_fcstd_document_xml(path, migrate)

            self.assertEqual(fcstd_technical_hashes(path), before)

    def test_fcstd_technical_hashes_detect_non_default_fuzzy_tolerance(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "part.FCStd"
            self.make_fcstd(path, "R0001")
            before = fcstd_technical_hashes(path)

            def add_fuzzy_tolerance(root):
                object_data = ElementTree.SubElement(root, "ObjectData")
                obj = ElementTree.SubElement(object_data, "Object", {"name": "Pad"})
                properties = ElementTree.SubElement(obj, "Properties", {"Count": "1"})
                fuzzy = ElementTree.SubElement(
                    properties,
                    "Property",
                    {"name": "FuzzyTolerance", "type": "App::PropertyLength"},
                )
                ElementTree.SubElement(fuzzy, "Float", {"value": "0.0100000000000000"})

            self.mutate_fcstd_document_xml(path, add_fuzzy_tolerance)

            self.assertNotEqual(
                fcstd_technical_hashes(path)["document_sha256"],
                before["document_sha256"],
            )

    def test_fcstd_technical_hashes_detect_attacher_type_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "part.FCStd"
            self.make_fcstd(path, "R0001")

            def add_attachment(root):
                object_data = ElementTree.SubElement(root, "ObjectData")
                obj = ElementTree.SubElement(object_data, "Object", {"name": "Sketch"})
                properties = ElementTree.SubElement(obj, "Properties", {"Count": "2"})
                engine = ElementTree.SubElement(
                    properties,
                    "Property",
                    {"name": "AttacherEngine", "type": "App::PropertyEnumeration"},
                )
                ElementTree.SubElement(engine, "Integer", {"value": "1"})
                attacher_type = ElementTree.SubElement(
                    properties,
                    "Property",
                    {"name": "AttacherType", "type": "App::PropertyString"},
                )
                ElementTree.SubElement(
                    attacher_type,
                    "String",
                    {"value": "Attacher::AttachEnginePlane"},
                )

            self.mutate_fcstd_document_xml(path, add_attachment)
            before = fcstd_technical_hashes(path)

            def change_attacher_type(root):
                value = root.find(
                    "./ObjectData/Object/Properties/Property[@name='AttacherType']/String"
                )
                value.attrib["value"] = "Attacher::AttachEngine3D"

            self.mutate_fcstd_document_xml(path, change_attacher_type)

            self.assertNotEqual(
                fcstd_technical_hashes(path)["document_sha256"],
                before["document_sha256"],
            )

    def test_fcstd_technical_hashes_detect_brep_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "part.FCStd"
            self.make_fcstd(path, "R0001")
            before = fcstd_technical_hashes(path)

            self.replace_fcstd_member(path, "PartShape.brp", b"changed-shape")

            self.assertNotEqual(fcstd_technical_hashes(path)["brep_sha256"], before["brep_sha256"])

    def test_technically_changed_manifest_files_ignores_gui_only_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "files" / "part.FCStd"
            path.parent.mkdir(parents=True)
            self.make_fcstd(path, "R0001")
            manifest = {
                "files": [
                    {
                        "path": "part.FCStd",
                        "revision_id": 10,
                        "revision_code": "R0001",
                        "sha256": sha256_file(path),
                        "is_root": True,
                    }
                ]
            }
            metadata = build_checkout_metadata(manifest, tmp)

            self.replace_fcstd_member(path, "GuiDocument.xml", b"<GuiDocument camera='changed' />")

            self.assertEqual(technically_changed_manifest_files(manifest, metadata, tmp), [])

    def test_technically_changed_manifest_files_ignores_brep_only_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "files" / "part.FCStd"
            path.parent.mkdir(parents=True)
            self.make_fcstd(path, "R0001")
            manifest = {
                "files": [
                    {
                        "path": "part.FCStd",
                        "revision_id": 10,
                        "revision_code": "R0001",
                        "sha256": sha256_file(path),
                        "is_root": True,
                    }
                ]
            }
            metadata = build_checkout_metadata(manifest, tmp)

            self.replace_fcstd_member(path, "PartShape.brp", b"rewritten-shape-cache")

            self.assertEqual(technically_changed_manifest_files(manifest, metadata, tmp), [])

    def test_technically_changed_manifest_files_detects_document_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "files" / "part.FCStd"
            path.parent.mkdir(parents=True)
            self.make_fcstd(path, "R0001")
            manifest = {
                "files": [
                    {
                        "path": "part.FCStd",
                        "revision_id": 10,
                        "revision_code": "R0001",
                        "sha256": sha256_file(path),
                        "is_root": True,
                    }
                ]
            }
            metadata = build_checkout_metadata(manifest, tmp)

            self.set_fcstd_string_property(path, "Label", "Changed label")
            changed = technically_changed_manifest_files(manifest, metadata, tmp)

            self.assertEqual(len(changed), 1)
            self.assertEqual(changed[0]["path"], "part.FCStd")
            self.assertEqual(changed[0]["revision_code"], "R0001")

    def test_external_cad_checkout_file_is_hash_checked_without_fcstd_parsing(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "files" / "vendor.step"
            path.parent.mkdir(parents=True)
            path.write_text("ISO-10303-21;", encoding="utf-8")
            manifest = {
                "files": [
                    {
                        "path": "vendor.step",
                        "revision_id": 10,
                        "revision_code": "R0001",
                        "file_format": "step",
                        "sha256": sha256_file(path),
                        "is_root": False,
                    }
                ]
            }
            metadata = build_checkout_metadata(manifest, tmp)

            self.assertEqual(metadata["files"][0]["file_format"], "step")
            self.assertEqual(technically_changed_manifest_files(manifest, metadata, tmp), [])

            path.write_text("locally changed", encoding="utf-8")
            with self.assertRaisesRegex(WorkspaceError, "schreibgeschützt"):
                technically_changed_manifest_files(manifest, metadata, tmp)

    def test_merge_checkout_metadata_preserves_existing_change_baseline(self):
        with tempfile.TemporaryDirectory() as tmp:
            files = Path(tmp) / "files"
            files.mkdir(parents=True)
            root_path = files / "Assembly.FCStd"
            added_path = files / "bigBottle.FCStd"
            self.make_fcstd(root_path, "R0001")
            initial_manifest = {
                "files": [
                    {
                        "path": "Assembly.FCStd",
                        "revision_id": 10,
                        "revision_code": "R0001",
                        "sha256": sha256_file(root_path),
                        "is_root": True,
                    }
                ]
            }
            metadata = build_checkout_metadata(initial_manifest, tmp)
            self.set_fcstd_string_property(root_path, "Label", "Locally changed")
            self.make_fcstd(added_path, "R0001")
            updated_manifest = {
                "files": [
                    *initial_manifest["files"],
                    {
                        "path": "bigBottle.FCStd",
                        "revision_id": 11,
                        "revision_code": "R0001",
                        "sha256": sha256_file(added_path),
                        "is_root": False,
                    },
                ]
            }

            merged = merge_checkout_metadata(updated_manifest, metadata, tmp)
            changed = technically_changed_manifest_files(updated_manifest, merged, tmp)

            self.assertEqual([item["path"] for item in merged["files"]], ["Assembly.FCStd", "bigBottle.FCStd"])
            self.assertEqual([item["path"] for item in changed], ["Assembly.FCStd"])

    def test_ensure_checkout_metadata_rejects_missing_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(WorkspaceError):
                ensure_checkout_metadata({"files": []}, tmp)

    def test_ensure_checkout_metadata_rejects_old_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_checkout_metadata(tmp, {"version": 1, "files": []})

            with self.assertRaises(WorkspaceError):
                ensure_checkout_metadata({"files": []}, tmp)

    def test_set_fcstd_plm_revision_updates_document_xml(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "part.FCStd"
            self.make_fcstd(path, "R0001")

            set_fcstd_plm_revision(path, "R0002")

            self.assertEqual(self.read_fcstd_plm_revision(path), "R0002")

    def test_update_changed_files_plm_revisions_uses_next_manifest_revision(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "part.FCStd"
            self.make_fcstd(path, "R0002")
            changed_files = [
                {
                    "path": "part.FCStd",
                    "local_path": path,
                    "revision_code": "R0002",
                }
            ]

            updated = update_changed_files_plm_revisions(changed_files)

            self.assertEqual(updated[0]["expected_revision_code"], "R0003")
            self.assertEqual(self.read_fcstd_plm_revision(path), "R0003")


if __name__ == "__main__":
    unittest.main()
