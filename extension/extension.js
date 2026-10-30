import Gio from 'gi://Gio';
import GLib from 'gi://GLib';

import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

const APP_ID = 'app.sdeb.StickyNotes';

// Pinned windows are matched by the exact title written to pinned.json.
// The default app uses XWayland hints instead; this covers a native Wayland run.

export default class StickyNotePins extends Extension {
    enable() {
        this._titles = new Set();
        this._tracked = new Map();
        this._managed = new Set();
        this._reloadId = 0;
        this._display = global.display;
        this._createdId = this._display.connect('window-created', (_display, win) => {
            this._track(win);
        });
        this._loadTitles();
        this._watchFile();
        for (const win of this._display.list_all_windows())
            this._track(win);
    }

    disable() {
        if (this._reloadId) {
            GLib.source_remove(this._reloadId);
            this._reloadId = 0;
        }
        if (this._createdId) {
            this._display.disconnect(this._createdId);
            this._createdId = 0;
        }
        if (this._monitor) {
            this._monitor.cancel();
            this._monitor = null;
        }
        const managed = [...this._managed];
        for (const [win, ids] of this._tracked) {
            for (const id of ids) {
                try {
                    win.disconnect(id);
                } catch (e) {
                    logError(e);
                }
            }
        }
        this._tracked.clear();
        this._titles = new Set();
        for (const win of managed)
            this._apply(win, false);
        this._managed.clear();
    }

    _file() {
        return Gio.File.new_for_path(GLib.build_filenamev([
            GLib.get_user_data_dir(),
            'app.sdeb.StickyNotes',
            'pinned.json',
        ]));
    }

    _watchFile() {
        const file = this._file();
        const parent = file.get_parent();
        try {
            if (!parent.query_exists(null))
                parent.make_directory_with_parents(null);
        } catch (e) {
            logError(e);
        }
        try {
            this._monitor = parent.monitor_directory(Gio.FileMonitorFlags.NONE, null);
            this._monitor.connect('changed', (_monitor, changed) => {
                if (!changed || changed.get_basename() === 'pinned.json')
                    this._scheduleReload();
            });
        } catch (e) {
            logError(e);
        }
    }

    _scheduleReload() {
        if (this._reloadId)
            return;
        this._reloadId = GLib.timeout_add(GLib.PRIORITY_DEFAULT, 150, () => {
            this._reloadId = 0;
            this._loadTitles();
            this._applyAll();
            return GLib.SOURCE_REMOVE;
        });
    }

    _loadTitles() {
        this._titles = new Set();
        try {
            const [ok, contents] = this._file().load_contents(null);
            if (!ok)
                return;
            const text = new TextDecoder().decode(contents);
            const data = JSON.parse(text);
            for (const title of data.titles || [])
                this._titles.add(title);
        } catch (e) {
            // Missing file is normal before the first pin.
        }
    }

    _isOurs(win) {
        try {
            if (win.get_gtk_application_id?.() === APP_ID)
                return true;
            const wm = win.get_wm_class?.() || '';
            return wm === APP_ID || wm === 'gnome-sticky-notes';
        } catch (e) {
            return false;
        }
    }

    _track(win) {
        if (!win || this._tracked.has(win))
            return;
        const ids = [
            win.connect('notify::title', () => this._apply(win)),
            win.connect('notify::gtk-application-id', () => this._apply(win)),
            win.connect('unmanaged', () => this._untrack(win)),
        ];
        this._tracked.set(win, ids);
        this._apply(win);
    }

    _untrack(win) {
        const ids = this._tracked.get(win);
        if (!ids)
            return;
        for (const id of ids) {
            try {
                win.disconnect(id);
            } catch (e) {
                logError(e);
            }
        }
        this._tracked.delete(win);
        this._managed.delete(win);
    }

    _applyAll() {
        for (const win of this._tracked.keys())
            this._apply(win);
    }

    _apply(win, forceWant = null) {
        if (!win)
            return;
        let want = false;
        try {
            if (!this._isOurs(win))
                return;
            const title = win.get_title() || '';
            want = forceWant === null ? this._titles.has(title) : forceWant;
            if (want) {
                if (!win.is_above())
                    win.make_above();
                if (!win.is_on_all_workspaces())
                    win.stick();
                this._managed.add(win);
            } else if (this._managed.has(win)) {
                if (win.is_above())
                    win.unmake_above();
                if (win.is_on_all_workspaces())
                    win.unstick();
                this._managed.delete(win);
            }
        } catch (e) {
            logError(e);
        }
    }
}
