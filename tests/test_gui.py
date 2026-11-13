# SPDX-FileCopyrightText: 2026 Maximilian Golser and Simon Dorrer
# SPDX-License-Identifier: Apache-2.0
"""GUI smoke test, runs offscreen. Skipped without Qt."""

import os
import tempfile
import unittest
from pathlib import Path

from tests import ROOT

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
try:
    from prep_ic.gui import main_window
    from prep_ic.gui.qt import QApplication
    from prep_ic.style import PALETTES
except ImportError:
    main_window = None


@unittest.skipIf(main_window is None, "Qt not installed")
class GuiSmoke(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        main_window.LAST_STATE = Path(self.tmp.name) / "last.json"
        self.win = main_window.MainWindow(PALETTES["light"], ROOT / "examples" / "padring.json")

    def tearDown(self):
        self.win.setWindowModified(False)
        self.win.close()
        self.tmp.cleanup()

    def test_loads_and_renders(self):
        import prep_ic as prep
        expected = prep.load(ROOT / "examples" / "padring.json")
        self.assertEqual(self.win.get_project(), expected)
        self.assertEqual(self.win.table.rowCount(), 0)  # filled only when the Pin List is shown
        self.win.tabs.setCurrentWidget(self.win.table_page)
        self.assertEqual(self.win.table.rowCount(), len(expected.layout().pins))
        self.win.editors["L"].set_text("A")
        self.win.render()
        self.assertEqual(self.win.table.rowCount(), len(self.win.layout_data.pins))
        self.assertEqual(self.win.editors["T"].text(), "\n".join(expected.physical_lines("T")))

    def test_reload_macros_keeps_what_the_file_dropped(self):
        import json
        path = Path(self.tmp.name) / "dropped.json"
        path.write_text(json.dumps({"sides": {"L": "A"}, "floorplan": {"macros": [{"name": "m", "io": None}]}}), encoding="utf-8")
        win = main_window.MainWindow(PALETTES["light"], path)
        try:
            dropped = "Macro entry 1 (m) could not be read and was dropped"
            self.assertIn(dropped, win.fp_warnings)
            win.reload_macros()  # F5
            self.assertIn(dropped, win.fp_warnings)
            win.editors["L"].set_text("A\nB")
            win.render()
            win._apply(win.get_project())  # an edit through the chip view keeps it too
            win.reload_macros()
            self.assertIn(dropped, win.fp_warnings)
        finally:
            win.setWindowModified(False)
            win.close()

    def test_editors_show_physical_order(self):
        # ccw: left 1–14 top → bottom, top numbered right → left, so its editor starts at 40
        self.assertEqual(self.win.editors["L"].edit.labels[:3], ["1", "2", "3"])
        self.assertEqual(self.win.editors["T"].edit.labels[:3], ["40", "39", "38"])
        self.assertEqual(self.win.editors["R"].edit.labels[0], "24")
        self.assertEqual(self.win.editors["B"].edit.labels[0], "15")
        import prep_ic as prep
        self.win.set_project(prep.Project.example())
        self.assertEqual(self.win.editors["T"].edit.labels, ["31", "30", "29–25", "24"])

    def test_mode_switch_keeps_editor_text(self):
        before = {s: e.text() for s, e in self.win.editors.items()}
        self.win.cb_mode.setCurrentIndex(self.win.cb_mode.findData("cw"))
        self.win.render()
        self.assertEqual({s: e.text() for s, e in self.win.editors.items()}, before)
        self.assertEqual(self.win.editors["T"].edit.labels[0], "1")

    def test_click_selects_editor_line(self):
        self.win.pad_clicked("T:0")  # first line in numbering order = rightmost pad = last editor line
        ed = self.win.editors["T"].edit
        self.assertEqual(ed.textCursor().blockNumber(), ed.blockCount() - 1)
        self.assertEqual(ed.textCursor().selectedText(), "VSSA_MIX")

    def test_fixed_die_setting(self):
        w = self.win
        self.assertFalse(w.sp_die_w.isEnabled())
        w.cb_die.setCurrentIndex(w.cb_die.findData("die"))  # starts from the current pad-limited size
        self.assertEqual((w.sp_die_w.value(), w.sp_die_h.value()), (1780.0, 1700.0))
        self.assertTrue(w.sp_die_w.isEnabled() and not w.chk_square.isEnabled())
        w.sp_die_w.setValue(2500)
        w.render()
        self.assertEqual(w.layout_data.die_width, 2500)
        self.assertEqual(w.stat_cap["die"].text(), "DIE (FIXED)")
        self.assertTrue(w.get_project().settings.fixed_die)
        w.cb_die.setCurrentIndex(w.cb_die.findData("pads"))
        w.render()
        self.assertEqual(w.layout_data.die_width, 1780)

    def test_fixed_core_setting(self):
        w = self.win
        self.assertFalse(w.sp_core_w.isEnabled())
        w.cb_die.setCurrentIndex(w.cb_die.findData("core"))
        self.assertTrue(w.sp_core_w.isEnabled() and w.chk_square.isEnabled() and not w.sp_die_w.isEnabled())
        w.chk_square.setChecked(False)
        w.sp_core_w.setValue(3000)
        w.sp_core_h.setValue(2500)
        w.sp_grid.setValue(5)
        w.render()
        st = w.get_project().settings
        self.assertEqual((st.fixed_core, st.fixed_die, st.core_width, st.core_height, st.grid),
                         (True, False, 3000.0, 2500.0, 5.0))
        self.assertEqual(w.layout_data.die_width, 3000 + 2 * w.layout_data.ring_depth)
        self.assertEqual(w.stat_cap["die"].text(), "DIE (MIN. CORE)")
        w.set_project(w.get_project())
        self.assertEqual(w.cb_die.currentData(), "core")

    def test_pdk_and_librelane_tab(self):
        w = self.win
        w.cb_pdk.setCurrentIndex(w.cb_pdk.findData("ihp-sg13g2"))
        self.assertFalse(w.sp[("std", "w")].isEnabled() or w.sp_cellh.isEnabled())
        self.assertGreaterEqual(w.sp[("std", "pitch")].value(), 80)
        w.render()
        self.assertEqual(w.layout_data.ring_depth, 320)
        self.assertTrue(all(p.cell for p in w.layout_data.pins))
        w.tabs.setCurrentWidget(w.ll_page)
        self.assertEqual(list(w.ll_texts), ["padring_config.yaml", "pad_cfg.tcl", "chip_top.sv",
                                            "chip_core_template.sv"])
        w.cb_pkg.setCurrentIndex(w.cb_pkg.findData("OP_QFN64_9x9mm_A4_FIT"))
        w.render()
        self.assertIn("PACKAGE_NAME: OP_QFN64_9x9mm_A4_FIT", w.ll_texts["bondplan_pinout.yaml"].toPlainText())
        self.assertEqual(w.get_project().settings.pdk, "ihp-sg13g2")

    def test_function_combo_rewrites_line(self):
        w = self.win
        w.cb_pdk.setCurrentIndex(w.cb_pdk.findData("ihp-sg13g2"))
        w.render()
        from prep_ic.gui.main_window import COL
        from PySide6.QtWidgets import QStyleOptionViewItem
        w.tabs.setCurrentWidget(w.table_page)
        self.assertIsNone(w.table.cellWidget(0, COL["Function"]))  # editors only while editing

        def edit(name, col, value):
            row = next(r for r, p in enumerate(w.layout_data.pins) if p.name == name)
            index = w.table.model().index(row, COL[col])
            d = w.table.itemDelegateForColumn(COL[col])
            editor = d.createEditor(w.table.viewport(), QStyleOptionViewItem(), index)
            d.setEditorData(editor, index)
            editor.setCurrentIndex(editor.findData(value))
            d.setModelData(editor, w.table.model(), index)

        edit("RST_N", "Function", "inout")
        self.assertIn("RST_N [io]", w.editors["L"].text())
        w.render()
        edit("RST_N", "Drive", 16)
        self.assertIn("RST_N [io] [16mA]", w.editors["L"].text())
        w.render()
        self.assertEqual(next(p.cell for p in w.layout_data.pins if p.name == "RST_N"), "sg13g2_IOPadInOut16mA")

    def test_layout_of_window(self):
        tabs = [self.win.tabs.tabText(i) for i in range(self.win.tabs.count())]
        self.assertEqual(tabs, ["Chip", "Pin List", "Settings", "LibreLane"])
        for mode in ("ccw", "cw"):
            self.win.cb_mode.setCurrentIndex(self.win.cb_mode.findData(mode))
            self.win.render()
            order = [self.win.ed_box.itemAt(i).widget().side for i in range(self.win.ed_box.count())]
            self.assertEqual(order, ["T", "R", "B", "L"])

    def test_select_pad(self):
        self.win.pad_clicked("L:2")
        self.win.tabs.setCurrentWidget(self.win.table_page)
        self.assertEqual(self.win.table.currentRow(), 2)

    def test_mode_switch_keeps_physical_order(self):
        before = [(p.name, p.cx, p.cy) for p in self.win.get_project().layout().pins]
        self.win.cb_mode.setCurrentIndex(self.win.cb_mode.findData("cw"))
        after = [(p.name, p.cx, p.cy) for p in self.win.get_project().layout().pins]
        self.assertEqual(sorted(before), sorted(after))

    def test_png(self):
        path = Path(self.tmp.name) / "ring.png"
        self.assertTrue(self.win.render_png(path, size=400))
        self.assertGreater(path.stat().st_size, 0)

    def test_logo_icon(self):
        from prep_ic.gui.app import LOGO
        from prep_ic.gui.qt import QIcon
        self.assertTrue(LOGO.is_file())
        # null without Qt's SVG plugins, which ship in PySide6-Essentials
        self.assertFalse(QIcon(str(LOGO)).pixmap(32, 32).isNull())

    def test_about_dialog(self):
        from unittest import mock
        from prep_ic import __version__
        from prep_ic.gui.about_dialog import AboutDialog
        shown = []

        class Probe(AboutDialog):
            def exec(self):  # modal exec would block the test
                shown.append(self)
                return 0

        about = self.win.act_about
        self.assertIn(about, self.win.help_menu.actions())
        self.assertEqual((self.win.help_menu.title(), about.text()), ("&Help", "About PREP-IC"))
        with mock.patch.object(main_window, "AboutDialog", Probe):
            about.trigger()
        dlg, = shown
        self.assertIs(dlg.parent(), self.win)
        self.assertIn(f"PREP-IC {__version__}", dlg.text.text())
        self.assertIn("Maximilian Golser and Simon Dorrer", dlg.text.text())
        self.assertFalse(dlg.logo.pixmap().isNull())
        dlg.close()


MACRO_DIR = ROOT / "tests" / "data" / "macros" / "adc_sar"


@unittest.skipIf(main_window is None, "Qt not installed")
class ChipGui(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        import prep_ic as prep
        self.tmp = tempfile.TemporaryDirectory()
        main_window.LAST_STATE = Path(self.tmp.name) / "last.json"
        self.win = main_window.MainWindow(PALETTES["light"])
        self.win.set_project(prep.Project())

    def tearDown(self):
        self.win.setWindowModified(False)
        self.win.close()
        self.tmp.cleanup()

    def lines(self, side):
        return self.win.editors[side].text().split("\n")

    def test_starts_on_chip_and_left_tabs(self):
        w = self.win
        self.assertEqual(w.tabs.tabText(w.tabs.currentIndex()), "Chip")
        self.assertEqual([w.left_tabs.tabText(i) for i in range(w.left_tabs.count())], ["Pads", "Macros"])
        self.assertIs(w.left_tabs.widget(1), w.macro_panel)

    def test_flylines_and_missing_pads(self):
        w = self.win
        w.add_macro_dir(str(MACRO_DIR))
        w.floorplan.macros[0].io += ["VIN_P", "VIN_N"]
        w.editors["L"].set_text("VIN_P")
        w.render()
        self.assertEqual(len(w.chip_items.flylines), 1)
        self.assertEqual(w.add_missing_pads(), ["VIN_N"])
        self.assertIn("VIN_N [analog]", self.lines("L"))
        self.assertEqual(len(w.chip_items.flylines), 2)
        self.assertTrue(w.get_project().settings.fixed_core)

    def test_move_pad_and_lock(self):
        w = self.win
        w.editors["L"].set_text("A\nB\nC")
        w.render()
        w.move_pad("L", 0, "T", 0)
        self.assertEqual((self.lines("L"), self.lines("T")), (["B", "C"], ["A"]))
        w.toggle_lock("L", 0)
        self.assertEqual(self.lines("L"), ["B [lock]", "C"])
        w.move_pad("L", 0, "L", 2)  # locked: nothing happens
        self.assertEqual(self.lines("L"), ["B [lock]", "C"])
        self.assertIn("locked", w.statusBar().currentMessage())

    def test_drop_pad_by_position(self):
        w = self.win
        w.editors["L"].set_text("A\nB\nC")
        w.render()
        lay = w.layout_data
        c = next(p for p in lay.pins if p.name == "C")
        w.drop_pad("L:0", lay.ring_depth / 2, lay.ring_depth + c.b + 1)  # below C on the left side
        self.assertEqual(self.lines("L"), ["B", "C", "A"])

    def test_optimize_and_stats(self):
        w = self.win
        w.add_macro_dir(str(MACRO_DIR))
        m = w.floorplan.macros[0]
        m.x, m.io = 400.0, ["VIN_P", "VIN_N"]
        w.editors["L"].set_text("VIN_N\nVIN_P")
        w.render()
        self.assertEqual(w.stat["cross"].text(), "1")
        w.optimize_pads()
        self.assertEqual(self.lines("L"), ["VIN_P", "VIN_N"])
        self.assertEqual(w.stat["cross"].text(), "0")

    def test_suggest_supplies_and_auto_rotate(self):
        w = self.win
        w.add_macro_dir(str(MACRO_DIR))
        self.assertEqual(w.suggest_supplies(), ["VDD", "VSS"])
        w.floorplan.macros[0].io = ["VIN_P", "VIN_N"]
        w.editors["T"].set_text("VIN_P\nVIN_N")
        w.floorplan.macros[0].x = 600.0
        w.render()
        self.assertEqual(w.auto_rotate("adc_sar0"), 90)

    def test_drag_snaps_to_grid_and_edges(self):
        w = self.win
        w.add_macro_dir(str(MACRO_DIR))
        w.add_placeholder("blk", 100.0, 100.0)
        w.floorplan.macros[1].x, w.floorplan.macros[1].y = 700.0, 600.0
        w.render()
        item = next(i for i in w.chip_items.macros if i.macro.name == "blk")
        x0, y0 = item.ctx["origin"]
        item.setPos(x0 + 433.0, y0 + 600.0)  # 13 µm right of adc_sar0's right edge (420): snaps to it
        self.assertEqual(w.floorplan.macros[1].x, 420.0)
        self.assertIsNotNone(item.ctx["guide"])
        item.setPos(x0 + 653.4, y0 + 600.0)
        self.assertEqual(w.floorplan.macros[1].x, 650.0)

    def test_double_click_rotates_every_time(self):
        from PySide6.QtCore import QPoint
        from PySide6.QtTest import QTest
        from prep_ic.gui.qt import Qt
        w = self.win
        w.resize(1200, 800)
        w.show()
        w.add_macro_dir(str(MACRO_DIR))
        self.app.processEvents()
        for expected in (90, 180):
            item = w.chip_items.macros[0]
            pos = w.view.mapFromScene(item.sceneBoundingRect().center())
            QTest.mouseDClick(w.view.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                              QPoint(pos.x(), pos.y()))
            QTest.qWait(50)
            self.assertEqual(w.floorplan.macros[0].rot, expected)
            QTest.qWait(700)

    def test_select_and_align(self):
        w = self.win
        w.add_placeholder("a", 100.0, 100.0)
        w.add_placeholder("b", 100.0, 100.0)
        w.floorplan.macros[1].x, w.floorplan.macros[1].y = 500.0, 300.0
        w.selected_macros = {"a", "b"}
        w.align("top")
        self.assertEqual([m.y for m in w.floorplan.macros], [0.0, 0.0])

    def test_rotate_duplicate_remove(self):
        w = self.win
        w.add_macro_dir(str(MACRO_DIR))
        m = w.floorplan.macros[0]
        w.rotate_macro(m)
        self.assertEqual((m.rot, m.size()), (90, (310.0, 420.0)))
        w.duplicate_macro(m)
        self.assertEqual([x.name for x in w.floorplan.macros], ["adc_sar0", "adc_sar1"])
        w.remove_macro(m)
        self.assertEqual([x.name for x in w.floorplan.macros], ["adc_sar1"])

    def test_macro_panel_fields(self):
        w = self.win
        w.add_macro_dir(str(MACRO_DIR))
        box = w.macro_panel.boxes[0]
        box.cls.setCurrentIndex(box.cls.findText("sensitive"))
        box.halo.setValue(50)
        p = w.get_project()
        self.assertEqual((p.floorplan.macros[0].cls, p.floorplan.macros[0].halo), ("sensitive", 50.0))

    def test_checks_settings(self):
        w = self.win
        w.sp_max_flyline.setValue(500)
        w.sp_spacing.setValue(42)
        st = w.get_project().settings
        self.assertEqual((st.max_flyline, st.spacing), (500.0, 42.0))
        w.set_project(w.get_project())
        self.assertEqual(w.sp_spacing.value(), 42.0)

    def test_layers(self):
        w = self.win
        w.add_macro_dir(str(MACRO_DIR))
        w.floorplan.macros[0].io = ["VIN_P"]
        w.editors["L"].set_text("VIN_P")
        w.render()
        self.assertEqual(len(w.chip_items.flylines), 1)
        w.layer_actions["flylines"].setChecked(False)
        self.assertEqual(len(w.chip_items.flylines), 0)

    def test_export_macros_button(self):
        w = self.win
        w.cb_pdk.setCurrentIndex(w.cb_pdk.findData("ihp-sg13g2"))
        w.add_macro_dir(str(MACRO_DIR))
        w.show_macros_export()
        self.assertIs(w.tabs.currentWidget(), w.ll_page)
        self.assertEqual(w.ll_tabs.tabText(w.ll_tabs.currentIndex()), "macros.yaml")

    def test_odd_instance_names_do_not_break_render(self):
        w = self.win
        w.add_macro_dir(str(MACRO_DIR))
        w.add_macro_dir(str(MACRO_DIR))
        w.floorplan.macros[0].name = "a and b"
        w.floorplan.macros[1].x = 0.0
        w.render()
        self.assertIn("Macros a and b and adc_sar1 overlap", w.warn.text())

    def test_warning_line_shows_crossings_and_unknown_tags(self):
        import prep_ic as prep
        w = self.win
        w.set_project(prep.load(ROOT / "examples" / "chip_demo.json"))
        self.assertIn("1 flyline crossing: VIN_P/VIN_N", w.warn.text())
        w.editors["L"].set_text("A [foo]")
        w.render()
        self.assertIn("Unknown tag or option in pad name: A [foo]", w.warn.text())


    def test_undo_add_missing_pads(self):
        w = self.win
        w.add_macro_dir(str(MACRO_DIR))
        w.floorplan.macros[0].io = ["VIN_P"]
        w.floorplan_changed(False)
        before = w.get_project()
        w.add_missing_pads()
        self.assertIn("VIN_P [analog]", self.lines("L"))
        w.undo()
        self.assertEqual(w.get_project(), before)
        w.redo()
        self.assertIn("VIN_P [analog]", self.lines("L"))

    def test_undo_redo_macro_drag(self):
        w = self.win
        w.add_macro_dir(str(MACRO_DIR))
        item = w.chip_items.macros[0]
        x0, y0 = item.ctx["origin"]
        item.ctx["on_press"](item.macro)
        item.setPos(x0 + 300.0, y0 + 200.0)
        item.ctx["on_release"](item.macro)
        self.assertEqual((w.floorplan.macros[0].x, w.floorplan.macros[0].y), (300.0, 200.0))
        w.undo()
        self.assertEqual((w.floorplan.macros[0].x, w.floorplan.macros[0].y), (0.0, 0.0))
        w.undo()  # adding the macro
        self.assertEqual(w.floorplan.macros, [])
        w.redo()
        w.redo()
        self.assertEqual(w.floorplan.macros[0].x, 300.0)

    def test_undo_typing_session(self):
        w = self.win
        w.editors["L"].set_text("A")
        w.commit()  # what losing the focus does
        w.editors["L"].set_text("A\nB")
        w.commit()
        w.undo()
        self.assertEqual(self.lines("L"), ["A"])

    def test_settings_are_no_undo_step(self):
        w = self.win
        w.editors["L"].set_text("A")
        w.commit()
        w.sp_spacing.setValue(42)
        w.editors["L"].set_text("A\nB")
        w.commit()
        w.undo()
        self.assertEqual((self.lines("L"), w.sp_spacing.value()), (["A"], 42.0))

    def test_undo_cleared_on_new(self):
        w = self.win
        w.editors["L"].set_text("A")
        w.commit()
        self.assertTrue(w.undo_stack)
        w.load_example()
        self.assertEqual((w.undo_stack, w.redo_stack), ([], []))

    def test_undo_keeps_leading_spacer_on_reversed_side(self):
        w = self.win  # ccw: the top side is numbered right to left, its first editor line is the last entry
        w.editors["T"].set_text("\nA\nB")
        w.commit()
        w.editors["L"].set_text("X")
        w.commit()
        w.undo()
        self.assertEqual(self.lines("T"), ["", "A", "B"])

    def test_measure_survives_redraw(self):
        from prep_ic.gui.qt import QPointF
        w = self.win
        w.measure_btn.setChecked(True)
        v = w.view
        v.measure_line(QPointF(0, 0), QPointF(300, 400))
        w.render()
        w.measure_btn.setChecked(False)  # raised RuntimeError on deleted items before
        self.assertIsNone(v._measure)

    def test_actions_keep_lef_warnings(self):
        import shutil
        w = self.win
        d = Path(self.tmp.name) / "adc_sar"
        shutil.copytree(MACRO_DIR, d)
        w.add_macro_dir(str(d))
        shutil.rmtree(d)
        w.reload_macros()
        self.assertIn("No LEF found", w.warn.text())
        w.editors["L"].set_text("A")
        w.toggle_lock("L", 0)
        self.assertIn("No LEF found", w.warn.text())

    def test_measure_tape(self):
        from prep_ic.gui.qt import QPointF
        w = self.win
        w.measure_btn.setChecked(True)
        n = len(w.scene.items())
        w.view.measure_line(QPointF(100, 100), QPointF(400, 500))
        self.assertIn("500.0 µm", w.view.measure_text())
        self.assertIn("Δx 300.0", w.view.measure_text())
        self.assertGreater(len(w.scene.items()) - n, 10)  # band, ticks, end marks, legs, label
        w.view.measure_line(QPointF(100, 100), QPointF(100, 160))
        self.assertIn("60.0 µm", w.view.measure_text())
        w.measure_btn.setChecked(False)
        self.assertEqual(len(w.scene.items()), n)

    def test_theme_switch(self):
        import json
        from prep_ic.gui.qt import QColor
        main_window.VIEW_SETTINGS = Path(self.tmp.name) / "view.json"
        w = self.win
        w.editors["L"].set_text("A")
        w.commit()
        w.setWindowModified(True)
        before = w.get_project()
        w.set_theme("dark")
        self.assertEqual(w.pal, PALETTES["dark"])
        self.assertEqual(w.scene.backgroundBrush().color(), QColor(PALETTES["dark"]["bg"]))
        self.assertEqual(w.get_project(), before)
        self.assertTrue(w.isWindowModified() and w.undo_stack)
        self.assertTrue(w.theme_actions["dark"].isChecked())
        self.assertEqual(json.loads(main_window.VIEW_SETTINGS.read_text())["theme"], "dark")
        w.set_theme("light")
        self.assertEqual(w.pal, PALETTES["light"])
        self.assertEqual(main_window.load_view_settings()["theme"], "light")

    def test_measure_tape_repaint_area_covers_the_band(self):
        # Qt repaints an item only inside its bounding rect; with cosmetic pens (width in pixels)
        # that rect is computed in µm, too small when zoomed out: moving the tape left traces
        from prep_ic.gui.qt import QPointF
        w = self.win
        w.resize(1200, 800)
        w.show()
        w.measure_btn.setChecked(True)
        self.app.processEvents()
        w.view.zoom(0.25, False)
        px = 1.0 / w.view.transform().m11()  # µm per pixel
        self.assertGreater(px, 3.0)  # zoomed out, as in the overview
        w.view.measure_line(QPointF(0, 500), QPointF(800, 500))  # horizontal tape
        for it in w.view._measure[1]:
            pen = it.pen() if hasattr(it, "pen") else None
            if pen is None or pen.widthF() <= 0 or not hasattr(it, "line"):
                continue
            drawn = pen.widthF() * (px if pen.isCosmetic() else 1.0)
            line = it.line()
            if abs(line.y1() - line.y2()) < 1e-9:  # horizontal: the height must hold the pen
                self.assertGreaterEqual(it.boundingRect().height() + 1e-6, drawn)

    def test_domain_bands_labelled(self):
        import prep_ic as prep
        from prep_ic.gui.qt import QGraphicsSimpleTextItem
        w = self.win
        w.set_project(prep.load(ROOT / "examples" / "chip_demo.json"))

        def texts():
            return [it.text() for it in w.scene.items() if isinstance(it, QGraphicsSimpleTextItem) and it.isVisible()]

        t = texts()
        self.assertGreaterEqual(t.count("ANA"), 3)  # left, top and right section
        self.assertGreaterEqual(t.count("DIG"), 1)
        self.assertFalse([x for x in t if x in ("[ANA]", "[DIG]")])  # no labels at the splits any more
        self.assertIn("ANA 20", w.stat["dom"].text())
        self.assertIn("DIG 13", w.stat["dom"].text())
        w.layer_actions["domains"].setChecked(False)
        self.assertNotIn("ANA", texts())

    def test_editor_keeps_trailing_spacers(self):
        w = self.win
        w.editors["L"].set_text("A\n\n")
        self.assertEqual(w.get_project().physical_lines("L"), ["A", "", ""])

    def test_drop_pad_into_empty_area(self):
        w = self.win
        w.cb_die.setCurrentIndex(w.cb_die.findData("core"))  # a pad-limited side has no empty area
        w.editors["L"].set_text("A\nB\nC")
        w.render()
        lay = w.layout_data
        before = {q.name: (q.cx, q.cy) for q in lay.pins}
        w.drop_pad("L:0", lay.ring_depth / 2, lay.die_height - lay.ring_depth - 30)  # bottom end of the left side
        after = {q.name: (q.cx, q.cy) for q in w.layout_data.pins}
        self.assertEqual((after["B"], after["C"]), (before["B"], before["C"]))
        self.assertEqual(self.lines("L")[-1], "A")
        self.assertEqual(self.lines("L")[0], "")

if __name__ == "__main__":
    unittest.main()
