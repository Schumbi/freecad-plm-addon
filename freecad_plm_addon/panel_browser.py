"""Project tree, selection and deep-link navigation."""

from pathlib import Path

from .panel_helpers import (
    active_checkout_revision_id,
    checkout_visual_state,
    revision_label,
    revision_workflow_hint,
)


class PanelBrowserMixin:
    def selected_project(self):
        item = self.tree_ancestor(self.browser_tree.currentItem(), "project")
        return self.tree_item_payload(item)

    def select_project_by_id(self, project_id):
        for item in self.iter_tree_items():
            project = self.tree_item_payload(item)
            if self.tree_item_kind(item) == "project" and project and project.get("id") == project_id:
                if hasattr(self, "project_search") and item.isHidden():
                    self.reset_project_filters()
                self.browser_tree.setCurrentItem(item)
                item.setExpanded(True)
                return True
        return False

    def selected_part(self):
        item = self.tree_ancestor(self.browser_tree.currentItem(), "part")
        return self.tree_item_payload(item)

    def select_part_by_id(self, part_id):
        for item in self.iter_tree_items():
            part = self.tree_item_payload(item)
            if self.tree_item_kind(item) == "part" and part and part.get("id") == part_id:
                if hasattr(self, "project_search") and item.isHidden():
                    self.reset_project_filters()
                self.browser_tree.setCurrentItem(item)
                item.setExpanded(True)
                return True
        return False

    def selected_revision(self):
        item = self.browser_tree.currentItem()
        if self.tree_item_kind(item) != "revision":
            return None
        return self.tree_item_payload(item)

    def selected_annotation(self):
        items = self.annotations.selectedItems()
        if not items:
            return None
        annotation = items[0].data(self.QtCore.Qt.UserRole)
        return annotation if isinstance(annotation, dict) else None

    def select_revision_by_id(self, revision_id):
        for item in self.iter_tree_items():
            revision = self.tree_item_payload(item)
            if self.tree_item_kind(item) == "revision" and revision and revision.get("id") == revision_id:
                self.browser_tree.setCurrentItem(item)
                return True
        return False

    def selected_active_checkout(self):
        return self.selected_tree_checkout()

    def tree_role(self, offset):
        return int(self.QtCore.Qt.UserRole) + offset

    def tree_item_kind(self, item):
        return item.data(0, self.tree_role(1)) if item is not None else ""

    def tree_item_payload(self, item):
        if item is None:
            return None
        payload = item.data(0, int(self.QtCore.Qt.UserRole))
        return payload if isinstance(payload, dict) else None

    def tree_item_checkout(self, item):
        if item is None:
            return None
        checkout = item.data(0, self.tree_role(3))
        return checkout if isinstance(checkout, dict) else None

    def tree_item_checkout_error(self, item):
        if item is None:
            return ""
        return str(item.data(0, self.tree_role(4)) or "")

    def selected_tree_checkout(self):
        return self.tree_item_checkout(self.browser_tree.currentItem())

    def tree_ancestor(self, item, kind):
        while item is not None:
            if self.tree_item_kind(item) == kind:
                return item
            item = item.parent()
        return None

    def iter_tree_items(self):
        pending = [
            self.browser_tree.topLevelItem(index)
            for index in range(self.browser_tree.topLevelItemCount())
        ]
        while pending:
            item = pending.pop(0)
            yield item
            pending[0:0] = [item.child(index) for index in range(item.childCount())]

    def find_tree_item(self, kind, entity_id, parent=None):
        for item in self.iter_tree_items():
            if self.tree_item_kind(item) != kind:
                continue
            payload = self.tree_item_payload(item) or {}
            if payload.get("id") != entity_id:
                continue
            if parent is None or self.tree_ancestor(item, self.tree_item_kind(parent)) is parent:
                return item
        return None

    def tree_selection_key(self):
        item = self.browser_tree.currentItem()
        payload = self.tree_item_payload(item) or {}
        kind = self.tree_item_kind(item)
        entity_id = payload.get("id")
        if not kind or entity_id is None:
            return None
        project = self.tree_item_payload(self.tree_ancestor(item, "project")) or {}
        part = self.tree_item_payload(self.tree_ancestor(item, "part")) or {}
        return (kind, entity_id, project.get("id"), part.get("id"))

    def restore_tree_selection(self, key):
        if not key:
            return False
        kind, entity_id = key[:2]
        project_id = key[2] if len(key) > 2 else None
        part_id = key[3] if len(key) > 3 else None
        project_item = self.find_tree_item("project", project_id) if project_id else None
        if project_item is not None and kind in ("part", "revision"):
            self.load_project_parts(project_item)
        part_item = (
            self.find_tree_item("part", part_id, project_item)
            if part_id is not None
            else None
        )
        if part_item is not None and kind == "revision":
            self.load_part_revisions(part_item)
        parent = part_item if kind == "revision" else project_item if kind == "part" else None
        item = self.find_tree_item(kind, entity_id, parent)
        if item is None:
            return False
        if project_item is not None:
            project_item.setExpanded(True)
        if part_item is not None:
            part_item.setExpanded(True)
        self.browser_tree.setCurrentItem(item)
        self.browser_tree.scrollToItem(item)
        return True

    def add_tree_item(self, parent, kind, payload, label, lazy=False):
        item = self.QtWidgets.QTreeWidgetItem([label])
        item.setData(0, int(self.QtCore.Qt.UserRole), payload)
        item.setData(0, self.tree_role(1), kind)
        item.setData(0, self.tree_role(2), not lazy)
        item.setData(0, self.tree_role(5), label)
        if parent is None:
            self.browser_tree.addTopLevelItem(item)
        else:
            parent.addChild(item)
        if lazy:
            placeholder = self.QtWidgets.QTreeWidgetItem(["Wird beim Aufklappen geladen …"])
            placeholder.setData(0, self.tree_role(1), "placeholder")
            item.addChild(placeholder)
        return item

    def remove_checkout_error_items(self):
        for top_index in range(self.browser_tree.topLevelItemCount() - 1, -1, -1):
            top_item = self.browser_tree.topLevelItem(top_index)
            if self.tree_item_kind(top_item) == "checkout_error":
                self.browser_tree.takeTopLevelItem(top_index)
                continue
            for child_index in range(top_item.childCount() - 1, -1, -1):
                if self.tree_item_kind(top_item.child(child_index)) == "checkout_error":
                    top_item.takeChild(child_index)

    def reset_checkout_tree_markers(self):
        self.remove_checkout_error_items()
        for item in self.iter_tree_items():
            if self.tree_item_kind(item) != "revision":
                continue
            base_label = item.data(0, self.tree_role(5)) or revision_label(
                self.tree_item_payload(item) or {}
            )
            item.setText(0, base_label)
            item.setData(0, self.tree_role(3), None)
            item.setData(0, self.tree_role(4), "")
            font = item.font(0)
            font.setBold(False)
            font.setItalic(False)
            item.setFont(0, font)
            item.setForeground(0, self.QtGui.QBrush())
            item.setIcon(0, self.QtGui.QIcon())
            item.setToolTip(0, revision_workflow_hint(self.tree_item_payload(item) or {}))

    def checkout_icon(self, state):
        filename = {
            "local": "checkout-local.svg",
            "server": "checkout-server.svg",
            "error": "checkout-error.svg",
        }.get(state)
        if not filename:
            return self.QtGui.QIcon()
        return self.QtGui.QIcon(str(Path(__file__).resolve().parent / "icons" / filename))

    def mark_checkout_item(self, item, checkout, error=""):
        state = checkout_visual_state(
            checkout,
            self.active_checkout_id(),
            bool(error),
        )
        labels = {
            "local": "Checkout lokal",
            "server": "Checkout auf Server",
            "error": "Checkout fehlerhaft",
        }
        colors = {
            "local": "#18794e",
            "server": "#9a6700",
            "error": "#c62828",
        }
        base_label = item.data(0, self.tree_role(5)) or item.text(0)
        item.setText(0, f"{base_label} · {labels[state]}")
        item.setData(0, self.tree_role(3), checkout)
        item.setData(0, self.tree_role(4), error)
        font = item.font(0)
        font.setBold(state == "local")
        font.setItalic(False)
        item.setFont(0, font)
        item.setForeground(0, self.QtGui.QBrush(self.QtGui.QColor(colors[state])))
        item.setIcon(0, self.checkout_icon(state))
        tooltip = labels[state]
        if error:
            tooltip = f"{tooltip}: {error}"
        item.setToolTip(0, tooltip)

    def add_checkout_error_item(self, parent, checkout, message):
        checkout_id = checkout.get("id") if isinstance(checkout, dict) else "?"
        item = self.add_tree_item(
            parent,
            "checkout_error",
            checkout,
            f"Checkout {checkout_id} konnte nicht zugeordnet werden",
        )
        item.setData(0, self.tree_role(3), checkout)
        item.setData(0, self.tree_role(4), message)
        font = item.font(0)
        font.setBold(True)
        item.setFont(0, font)
        item.setForeground(0, self.QtGui.QBrush(self.QtGui.QColor("#c62828")))
        item.setIcon(0, self.checkout_icon("error"))
        item.setToolTip(0, message)
        if parent is not None:
            parent.setExpanded(True)
        return item

    def reveal_active_checkouts(self):
        self.reset_checkout_tree_markers()
        checkout_items = {}
        for checkout in self.server_checkouts:
            checkout_id = checkout.get("id")
            project = checkout.get("project") or {}
            part = checkout.get("part") or {}
            revision_id = active_checkout_revision_id(checkout)
            project_item = self.find_tree_item("project", project.get("id"))
            if project_item is None:
                checkout_items[checkout_id] = self.add_checkout_error_item(
                    None,
                    checkout,
                    "Projekt des aktiven Checkouts wurde nicht gefunden.",
                )
                continue
            self.load_project_parts(project_item)
            part_item = self.find_tree_item("part", part.get("id"), project_item)
            if part_item is None:
                checkout_items[checkout_id] = self.add_checkout_error_item(
                    project_item,
                    checkout,
                    "Teil des aktiven Checkouts wurde im Projekt nicht gefunden.",
                )
                continue
            self.load_part_revisions(part_item)
            revision_item = self.find_tree_item("revision", revision_id, part_item)
            if revision_item is None:
                checkout_items[checkout_id] = self.add_checkout_error_item(
                    project_item,
                    checkout,
                    "Revision des aktiven Checkouts wurde im Teil nicht gefunden.",
                )
                continue
            error = self.checkout_errors.get(checkout_id, "")
            self.mark_checkout_item(revision_item, checkout, error)
            project_item.setExpanded(True)
            part_item.setExpanded(True)
            checkout_items[checkout_id] = revision_item
        self.checkout_tree_items = checkout_items
        return checkout_items

    def clear_tree_children(self, item):
        while item is not None and item.childCount():
            item.takeChild(0)

    def browser_selection_changed(self):
        item = self.browser_tree.currentItem()
        kind = self.tree_item_kind(item)
        project = self.selected_project()
        part = self.selected_part()
        revision = self.selected_revision()

        self.clear_project_form()
        self.clear_part_form()
        self.clear_revision_context()
        if project:
            self.set_project_form(project)
        if part:
            self.set_part_form(part)
        if revision:
            self.set_revision_context(revision)
        self.update_context_actions()
        if kind == "project":
            self.set_status("Projekt ausgewählt. Zum Laden der Teile aufklappen.")
        elif kind == "part":
            self.set_status("Teil ausgewählt. Zum Laden der Revisionen aufklappen.")

    def browser_item_expanded(self, item):
        if bool(item.data(0, self.tree_role(2))):
            return
        kind = self.tree_item_kind(item)
        if kind == "project":
            self.load_project_parts(item)
        elif kind == "part":
            self.load_part_revisions(item)

    def browser_item_double_clicked(self, item, _column=0):
        kind = self.tree_item_kind(item)
        if kind == "checkout_error":
            self.refresh_projects()
            return
        if kind != "revision":
            return
        checkout = self.tree_item_checkout(item)
        state = checkout_visual_state(
            checkout,
            self.active_checkout_id(),
            bool(self.tree_item_checkout_error(item)),
        )
        if state == "local":
            self.open_active_checkout_root()
        elif state in ("server", "error"):
            self.reopen_selected_checkout()
        else:
            self.open_selected_revision()

    def show_browser_context_menu(self, position):
        item = self.browser_tree.itemAt(position)
        if item is None or self.tree_item_kind(item) == "placeholder":
            return
        self.browser_tree.setCurrentItem(item)
        self.update_context_actions()
        menu = self.QtWidgets.QMenu(self.browser_tree)
        if self.context_primary_label and callable(self.context_primary_callback):
            menu.addAction(self.context_primary_label, self.context_primary_callback)
        if self.context_more_actions:
            menu.addSeparator()
        for label, callback in self.context_more_actions:
            if label is None:
                menu.addSeparator()
            else:
                menu.addAction(label, callback)
        menu.exec_(self.browser_tree.viewport().mapToGlobal(position))

    def handle_revision_deep_link(self, deep_link):
        self.refresh_projects()
        project_item = next(
            (
                item
                for item in self.iter_tree_items()
                if self.tree_item_kind(item) == "project"
                and (self.tree_item_payload(item) or {}).get("id")
                == deep_link.project_id
            ),
            None,
        )
        if project_item is None:
            self.set_status("Projekt aus dem PLM-Link wurde nicht gefunden.")
            return False
        self.load_project_parts(project_item)
        part_item = next(
            (
                item
                for item in self.iter_tree_items()
                if self.tree_item_kind(item) == "part"
                and (self.tree_item_payload(item) or {}).get("id") == deep_link.part_id
                and self.tree_ancestor(item, "project") is project_item
            ),
            None,
        )
        if part_item is None:
            self.set_status("Teil aus dem PLM-Link wurde im Projekt nicht gefunden.")
            return False
        self.load_part_revisions(part_item)
        revision_item = next(
            (
                item
                for item in self.iter_tree_items()
                if self.tree_item_kind(item) == "revision"
                and (self.tree_item_payload(item) or {}).get("id")
                == deep_link.revision_id
                and self.tree_ancestor(item, "part") is part_item
            ),
            None,
        )
        if revision_item is None:
            self.set_status("Revision aus dem PLM-Link wurde im Teil nicht gefunden.")
            return False
        self.browser_tree.setCurrentItem(revision_item)
        self.browser_tree.scrollToItem(revision_item)

        if deep_link.action == "checkout":
            revision = self.selected_revision() or {}
            answer = self.QtWidgets.QMessageBox.question(
                self.widget,
                "Revision auschecken",
                f"{revision_label(revision)} wirklich zum Bearbeiten auschecken?",
                self.QtWidgets.QMessageBox.Yes | self.QtWidgets.QMessageBox.No,
                self.QtWidgets.QMessageBox.No,
            )
            if answer != self.QtWidgets.QMessageBox.Yes:
                self.set_status("Checkout aus PLM-Link abgebrochen.")
                return False
            self.checkout_selected_revision()
        elif deep_link.action == "slicer":
            self.open_selected_revision_in_slicer()
        else:
            self.open_selected_revision_readonly()
        return True
