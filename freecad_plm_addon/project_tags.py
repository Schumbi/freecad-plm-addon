"""Project tag presentation and local filtering (also works with older servers)."""

def project_tag_names(project):
    return [tag["name"] for tag in project.get("tags", []) if isinstance(tag, dict) and tag.get("name")]


def project_matches(project, query="", selected=(), mode="all", untagged=False):
    tags = {name.casefold() for name in project_tag_names(project)}
    selected = {name.casefold() for name in selected}
    text = " ".join(str(project.get(key) or "") for key in ("code", "name", "description"))
    if query.strip().casefold() not in (text + " " + " ".join(tags)).casefold():
        return False
    if untagged:
        return not tags
    return not selected or (bool(tags & selected) if mode == "any" else selected <= tags)


class PanelProjectTagsMixin:
    def build_project_filters(self, layout):
        widgets = self.QtWidgets
        self.project_search = widgets.QLineEdit()
        self.project_search.setPlaceholderText("Projekte suchen: Name, Code oder Tag …")
        layout.addWidget(self.project_search)
        row = widgets.QHBoxLayout()
        self.project_tag_button = widgets.QToolButton()
        self.project_tag_button.setText("Tags: Alle")
        self.project_tag_menu = widgets.QMenu(self.project_tag_button)
        self.project_tag_button.setMenu(self.project_tag_menu)
        self.project_tag_button.setPopupMode(widgets.QToolButton.InstantPopup)
        self.project_tag_actions = []
        self.project_tag_mode = widgets.QComboBox()
        self.project_tag_mode.addItem("UND", "all")
        self.project_tag_mode.addItem("ODER", "any")
        self.project_tag_mode.addItem("Ohne Tags", "untagged")
        self.project_tag_mode.setToolTip("UND: alle ausgewählten Tags; ODER: mindestens eines")
        reset = widgets.QPushButton("Alle")
        reset.setToolTip("Alle Projekte anzeigen und Filter zurücksetzen")
        row.addWidget(self.project_tag_button)
        row.addWidget(self.project_tag_mode)
        row.addWidget(reset)
        layout.addLayout(row)
        self.project_filter_count = widgets.QLabel()
        layout.addWidget(self.project_filter_count)
        self.project_search.textChanged.connect(self.apply_project_filters)
        self.project_tag_mode.currentIndexChanged.connect(self.apply_project_filters)
        reset.clicked.connect(self.reset_project_filters)

    def update_project_tag_options(self):
        if not hasattr(self, "project_tag_menu"):
            return
        selected = {a.data() for a in self.project_tag_actions if a.isChecked()}
        counts = {}
        for item in self.iter_tree_items():
            if self.tree_item_kind(item) == "project":
                for name in project_tag_names(self.tree_item_payload(item)):
                    counts[name] = counts.get(name, 0) + 1
        self.project_tag_menu.clear()
        self.project_tag_actions = []
        for name, count in sorted(counts.items(), key=lambda entry: entry[0].casefold()):
            action = self.project_tag_menu.addAction(f"{name} ({count})")
            action.setCheckable(True)
            action.setData(name)
            action.setChecked(name in selected)
            action.toggled.connect(self.apply_project_filters)
            self.project_tag_actions.append(action)
        if not counts:
            self.project_tag_menu.addAction("Noch keine Tags").setEnabled(False)
        self.apply_project_filters()

    def reset_project_filters(self, *_args):
        self.project_search.clear()
        self.project_tag_mode.setCurrentIndex(0)
        for action in self.project_tag_actions:
            action.setChecked(False)
        self.apply_project_filters()

    def apply_project_filters(self, *_args):
        if not hasattr(self, "project_search"):
            return
        selected = [a.data() for a in self.project_tag_actions if a.isChecked()]
        mode = self.project_tag_mode.currentData()
        visible = total = 0
        for item in self.iter_tree_items():
            if self.tree_item_kind(item) != "project":
                continue
            total += 1
            matches = project_matches(self.tree_item_payload(item), self.project_search.text(),
                selected, mode, mode == "untagged")
            item.setHidden(not matches)
            visible += int(matches)
            if not matches and self.tree_ancestor(self.browser_tree.currentItem(), "project") is item:
                self.browser_tree.setCurrentItem(None)
        self.project_tag_button.setText(f"Tags ({len(selected)})" if selected else "Tags: Alle")
        self.project_tag_button.setToolTip(", ".join(selected) or "Tags auswählen")
        self.project_filter_count.setText(f"{visible} von {total} Projekten")


def install_tag_completer(edit, QtCore, QtWidgets, names):
    class TagCompleter(QtWidgets.QCompleter):
        def splitPath(self, path):
            return [path.rsplit(",", 1)[-1].strip()]

        def pathFromIndex(self, index):
            completion = super().pathFromIndex(index)
            prefix, separator, _last = edit.text().rpartition(",")
            return prefix + ", " + completion if separator else completion

    completer = TagCompleter(sorted(set(names), key=str.casefold), edit)
    completer.setCaseSensitivity(QtCore.Qt.CaseInsensitive)
    edit.setCompleter(completer)
    return completer
