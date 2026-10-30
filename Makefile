.PHONY: test run install dist package

test:
	python3 -m unittest discover -s tests -v

run:
	./bin/gnome-sticky-notes

install:
	./install.sh

dist:
	tar --exclude-vcs \
		--exclude='__pycache__' --exclude='*.py[cod]' \
		--exclude=PKGBUILD --exclude=gnome-sticky-notes.install --exclude=.SRCINFO \
		--exclude='*.tar.gz' --exclude='*.pkg.tar.*' \
		--exclude=src --exclude=pkg --exclude=dist --exclude='*.egg-info' \
		-caf gnome-sticky-notes-1.0.0.tar.gz \
		--transform 's,^,gnome-sticky-notes-1.0.0/,' \
		bin data extension gnome_sticky_notes tests README.md LICENSE pyproject.toml .gitignore Makefile install.sh

package: dist
	sum=$$(sha256sum gnome-sticky-notes-1.0.0.tar.gz | awk '{print $$1}'); \
	sed -i "s/^sha256sums=.*/sha256sums=('$$sum')/" PKGBUILD
	makepkg --printsrcinfo > .SRCINFO
	makepkg -f
