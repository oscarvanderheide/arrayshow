import datetime
import os
import subprocess
import uuid

import matplotlib.pyplot as plt
import numpy as np

__all__ = ["ArrayView"]


image_plot_help_str = r"""
$\bf{Hotkeys:}$
    $\bf{h:}$ show/hide hotkey menu.
    $\bf{x/y/z:}$ set current axis as x/y/z.
    $\bf{t:}$ swap between x and y.
    $\bf{c:}$ cycle colormaps.
    $\bf{left/right:}$ change current axis.
    $\bf{up/down:}$ change slice along current axis.
    $\bf{a:}$ toggle hide all labels, titles and axes.
    $\bf{m/p/r/i/l:}$  magnitude/phase/real/imaginary/log mode.
    $\bf{[/]:}$ change brightness.
    $\bf{\{/\}:}$ change contrast.
    $\bf{s:}$ save as png.
    $\bf{g/v:}$ save as gif/video by along current axis.
    $\bf{q:}$ refresh.
    $\bf{0-9:}$ enter slice number.
    $\bf{enter:}$ set current axis as slice number.
"""


class ArrayView(object):
    """Plot array as image.

    Press 'h' for a menu for hotkeys.

    Args:
        im (array): image numpy/cupy array.
        x (int): x axis.
        y (int): y axis.
        z (None or int): z axis.
        c (None or int): color axis.
        hide_axes (bool): toggle hiding axes, labels and title.
        mode (str): specify magnitude, phase, real, imaginary,
            and log mode. {'m', 'p', 'r', 'i', 'l'}.
        title (str): title.
        interpolation (str): plot interpolation.
        save_basename (str): saved png, gif, and video base name.
        fps (int): frame per seconds for gif and video.

    """

    def __init__(
        self,
        im,
        x=-1,
        y=-2,
        z=None,
        c=None,
        hide_axes=False,
        mode=None,
        colormap=None,
        vmin=None,
        vmax=None,
        title="",
        interpolation="nearest",
        save_basename="Figure",
        fps=10,
    ):
        if im.ndim < 2:
            raise TypeError(
                "Image dimension must at least be two, got {im_ndim}".format(
                    im_ndim=im.ndim
                )
            )

        self.axim = None
        self.im = im
        self.fig = plt.figure()
        self.ax = self.fig.add_subplot(111)
        self.shape = self.im.shape
        self.ndim = self.im.ndim
        self.slices = [s // 2 for s in self.shape]
        self.flips = [1] * self.ndim
        self.x = x % self.ndim
        self.y = y % self.ndim
        self.z = z % self.ndim if z is not None else None
        self.c = c % self.ndim if c is not None else None
        self.d = max(self.ndim - 3, 0)
        self.hide_axes = hide_axes
        self.show_help = False
        self.title = title
        self.interpolation = interpolation
        self.mode = mode
        self.colormaps = ["gray", "viridis", "RdBu_r", "magma"]
        self.colormap_idx = 0
        if colormap is not None:
            try:
                self.colormap_idx = self.colormaps.index(colormap)
            except ValueError:
                pass  # Keep default if not in list
        self.colormap = self.colormaps[self.colormap_idx]
        self.entering_slice = False
        self.vmin = vmin
        self.vmax = vmax
        self.save_basename = save_basename
        self.fps = fps
        self.help_text = None

        self.fig.canvas.mpl_disconnect(self.fig.canvas.manager.key_press_handler_id)
        self.fig.canvas.mpl_connect("key_press_event", self.key_press)
        self.update_axes()
        self.update_image()
        self.fig.canvas.draw()
        plt.show(block=True)

    def key_press(self, event):
        if event.key == "c":
            self.colormap_idx = (self.colormap_idx + 1) % len(self.colormaps)
            self.colormap = self.colormaps[self.colormap_idx]
            self.update_image()
            self.fig.canvas.draw()
        elif event.key == "up":
            if self.d not in [self.x, self.y, self.z, self.c]:
                self.slices[self.d] = (self.slices[self.d] + 1) % self.shape[self.d]
            else:
                self.flips[self.d] *= -1

            self.update_axes()
            self.update_image()
            self.fig.canvas.draw()

        elif event.key == "down":
            if self.d not in [self.x, self.y, self.z, self.c]:
                self.slices[self.d] = (self.slices[self.d] - 1) % self.shape[self.d]
            else:
                self.flips[self.d] *= -1

            self.update_axes()
            self.update_image()
            self.fig.canvas.draw()

        elif event.key == "left":
            self.d = (self.d - 1) % self.ndim

            self.update_axes()
            self.fig.canvas.draw()

        elif event.key == "right":
            self.d = (self.d + 1) % self.ndim

            self.update_axes()
            self.fig.canvas.draw()

        elif event.key == "x" and self.d not in [self.x, self.z, self.c]:
            if self.d == self.y:
                self.x, self.y = self.y, self.x
            else:
                self.x = self.d

            self.update_axes()
            self.update_image()
            self.fig.canvas.draw()

        elif event.key == "y" and self.d not in [self.y, self.z, self.c]:
            if self.d == self.x:
                self.x, self.y = self.y, self.x
            else:
                self.y = self.d

            self.update_axes()
            self.update_image()
            self.fig.canvas.draw()

        elif event.key == "z" and self.d not in [self.x, self.y, self.c]:
            if self.d == self.z:
                self.z = None
            else:
                self.z = self.d

            self.update_axes()
            self.update_image()
            self.fig.canvas.draw()

        elif event.key == "t":
            self.x, self.y = self.y, self.x

            self.update_axes()
            self.update_image()
            self.fig.canvas.draw()

        elif event.key == "a":
            self.hide_axes = not self.hide_axes

            self.update_axes()
            self.fig.canvas.draw()

        elif event.key == "f":
            self.fig.canvas.manager.full_screen_toggle()

        elif event.key == "q":
            self.vmin = None
            self.vmax = None
            self.update_axes()
            self.update_image()
            self.fig.canvas.draw()

        elif event.key == "]":
            width = self.vmax - self.vmin
            self.vmin -= width * 0.1
            self.vmax -= width * 0.1

            self.update_image()
            self.fig.canvas.draw()

        elif event.key == "[":
            width = self.vmax - self.vmin
            self.vmin += width * 0.1
            self.vmax += width * 0.1

            self.update_image()
            self.fig.canvas.draw()

        elif event.key == "}":
            width = self.vmax - self.vmin
            center = (self.vmax + self.vmin) / 2
            self.vmin = center - width * 1.1 / 2
            self.vmax = center + width * 1.1 / 2

            self.update_image()
            self.fig.canvas.draw()

        elif event.key == "{":
            width = self.vmax - self.vmin
            center = (self.vmax + self.vmin) / 2
            self.vmin = center - width * 0.9 / 2
            self.vmax = center + width * 0.9 / 2

            self.update_image()
            self.fig.canvas.draw()

        elif event.key in ["m", "p", "r", "i", "l"]:
            self.vmin = None
            self.vmax = None
            self.mode = event.key

            self.update_axes()
            self.update_image()
            self.fig.canvas.draw()

        elif event.key == "s":
            filename = self.save_basename + datetime.datetime.now().strftime(
                " %Y-%m-%d at %I.%M.%S %p.png"
            )
            self.fig.savefig(
                filename,
                transparent=True,
                format="png",
                bbox_inches="tight",
                pad_inches=0,
            )

        elif event.key == "g":
            filename = self.save_basename + datetime.datetime.now().strftime(
                " %Y-%m-%d at %I.%M.%S %p.gif"
            )
            temp_basename = uuid.uuid4()

            bbox = self.fig.get_tightbbox(self.fig.canvas.get_renderer())
            for i in range(self.shape[self.d]):
                self.slices[self.d] = i

                self.update_axes()
                self.update_image()
                self.fig.canvas.draw()
                self.fig.savefig(
                    "{} {:05d}.png".format(temp_basename, i),
                    format="png",
                    bbox_inches=bbox,
                    pad_inches=0,
                )

            subprocess.run(
                [
                    "ffmpeg",
                    "-f",
                    "image2",
                    "-s",
                    "{}x{}".format(
                        int(bbox.width * self.fig.dpi),
                        int(bbox.height * self.fig.dpi),
                    ),
                    "-framerate",
                    str(self.fps),
                    "-i",
                    "{} %05d.png".format(temp_basename),
                    "-vf",
                    "palettegen",
                    "{} palette.png".format(temp_basename),
                ]
            )
            subprocess.run(
                [
                    "ffmpeg",
                    "-f",
                    "image2",
                    "-s",
                    "{}x{}".format(
                        int(bbox.width * self.fig.dpi),
                        int(bbox.height * self.fig.dpi),
                    ),
                    "-framerate",
                    str(self.fps),
                    "-i",
                    "{} %05d.png".format(temp_basename),
                    "-i",
                    "{} palette.png".format(temp_basename),
                    "-lavfi",
                    "paletteuse",
                    filename,
                ]
            )

            os.remove("{} palette.png".format(temp_basename))
            for i in range(self.shape[self.d]):
                os.remove("{} {:05d}.png".format(temp_basename, i))

        elif event.key == "v":
            filename = self.save_basename + datetime.datetime.now().strftime(
                " %Y-%m-%d at %I.%M.%S %p.mp4"
            )
            temp_basename = uuid.uuid4()

            for i in range(self.shape[self.d]):
                self.slices[self.d] = i

                self.update_axes()
                self.update_image()
                self.fig.canvas.draw()
                self.fig.savefig(
                    "{} {:05d}.png".format(temp_basename, i),
                    format="png",
                    transparent=True,
                    bbox_inches="tight",
                    pad_inches=0,
                )

            subprocess.run(
                [
                    "ffmpeg",
                    "-r",
                    str(self.fps),
                    "-i",
                    "{} %05d.png".format(temp_basename),
                    "-vf",
                    "crop=floor(iw/2)*2-10:floor(ih/2)*2-10",
                    "-pix_fmt",
                    "yuv420p",
                    "-crf",
                    "1",
                    "-vcodec",
                    "libx264",
                    "-preset",
                    "veryslow",
                    filename,
                ]
            )

            for i in range(self.shape[self.d]):
                os.remove("{} {:05d}.png".format(temp_basename, i))

        elif event.key in [
            "0",
            "1",
            "2",
            "3",
            "4",
            "5",
            "6",
            "7",
            "8",
            "9",
            "backspace",
        ] and self.d not in [self.x, self.y, self.z, self.c]:
            if self.entering_slice:
                if event.key == "backspace":
                    if self.entered_slice < 10:
                        self.entering_slice = False
                    else:
                        self.entered_slice //= 10
                else:
                    self.entered_slice = self.entered_slice * 10 + int(event.key)
            elif event.key != "backspace":
                self.entering_slice = True
                self.entered_slice = int(event.key)

            self.update_axes()
            self.fig.canvas.draw()

        elif event.key == "enter" and self.entering_slice:
            self.entering_slice = False
            if self.entered_slice < self.shape[self.d]:
                self.slices[self.d] = self.entered_slice

                self.update_image()

            self.update_axes()
            self.fig.canvas.draw()

        elif event.key == "h":
            self.show_help = not self.show_help

            self.update_image()
            self.fig.canvas.draw()
        else:
            return

    def update_image(self):
        # Extract slice.
        idx = []
        for i in range(self.ndim):
            if i in [self.x, self.y, self.z, self.c]:
                idx.append(slice(None, None, self.flips[i]))
            else:
                idx.append(self.slices[i])

        idx = tuple(idx)
        imv = self.im[idx]

        # Transpose to have [z, y, x, c].
        imv_dims = [self.y, self.x]
        if self.z is not None:
            imv_dims = [self.z] + imv_dims

        if self.c is not None:
            imv_dims = imv_dims + [self.c]

        imv = np.transpose(imv, np.argsort(np.argsort(imv_dims)))
        imv = array_to_image(imv, color=self.c is not None)

        if self.mode is None:
            if np.isrealobj(imv):
                self.mode = "r"
            else:
                self.mode = "m"

        if self.mode == "m":
            imv = np.abs(imv)
        elif self.mode == "p":
            imv = np.angle(imv)
        elif self.mode == "r":
            imv = np.real(imv)
        elif self.mode == "i":
            imv = np.imag(imv)
        elif self.mode == "l":
            imv = np.abs(imv)
            imv = np.log(imv, out=np.ones_like(imv) * -31, where=imv != 0)

        if self.vmin is None:
            self.vmin = imv.min()

        if self.vmax is None:
            self.vmax = imv.max()

        if self.axim is None:
            if self.colormap is None:
                colormap = "gray"
            else:
                colormap = self.colormap
            self.axim = self.ax.imshow(
                imv,
                vmin=self.vmin,
                vmax=self.vmax,
                cmap=colormap,
                origin="lower",
                interpolation=self.interpolation,
                aspect=1.0,
                extent=[0, imv.shape[1], 0, imv.shape[0]],
            )

            # Add colorbar and keep reference
            if self.colormap is not None:
                self.colorbar = self.fig.colorbar(self.axim)
            else:
                self.colorbar = None
        else:
            self.axim.set_data(imv)
            self.axim.set_extent([0, imv.shape[1], 0, imv.shape[0]])
            self.axim.set_clim(self.vmin, self.vmax)
            # Update colormap
            self.axim.set_cmap(self.colormap)
            # Remove and redraw colorbar if present
            if hasattr(self, "colorbar") and self.colorbar is not None:
                self.colorbar.remove()
                self.colorbar = self.fig.colorbar(self.axim)

        if self.help_text is None:
            bbox_props = dict(boxstyle="round", pad=1, fc="white", alpha=0.95, lw=0)
            self.help_text = self.ax.text(
                imv.shape[0] / 2,
                imv.shape[1] / 2,
                image_plot_help_str,
                ha="center",
                va="center",
                linespacing=1.5,
                ma="left",
                size=8,
                bbox=bbox_props,
            )

        self.help_text.set_visible(self.show_help)

    def update_axes(self):
        if not self.hide_axes:
            caption = "["
            for i in range(self.ndim):
                if i == self.d:
                    caption += "["
                else:
                    caption += " "

                if self.flips[i] == -1 and (
                    i == self.x or i == self.y or i == self.z or i == self.c
                ):
                    caption += "-"

                if i == self.x:
                    caption += "x"
                elif i == self.y:
                    caption += "y"
                elif i == self.z:
                    caption += "z"
                elif i == self.c:
                    caption += "c"
                elif i == self.d and self.entering_slice:
                    caption += str(self.entered_slice) + "_"
                else:
                    caption += str(self.slices[i])

                if i == self.d:
                    caption += "]"
                else:
                    caption += " "
            caption += "]"

            self.ax.set_title(caption)
            self.fig.suptitle(self.title)
            self.ax.xaxis.set_visible(True)
            self.ax.yaxis.set_visible(True)
            self.ax.title.set_visible(True)
        else:
            self.ax.set_title("")
            self.fig.suptitle("")
            self.ax.xaxis.set_visible(False)
            self.ax.yaxis.set_visible(False)
            self.ax.title.set_visible(False)


def mosaic_shape(batch):
    mshape = [int(batch**0.5), batch // int(batch**0.5)]

    while np.prod(mshape) < batch:
        mshape[1] += 1

    if (mshape[0] - 1) * (mshape[1] + 1) == batch:
        mshape[0] -= 1
        mshape[1] += 1

    return tuple(mshape)


def array_to_image(arr, color=False):
    """
    Flattens all dimensions except the last two

    Args:
        arr (array): shape [z, x, y, c] if color, else [z, x, y]

    """
    if color and not (arr.max() == 0 and arr.min() == 0):
        arr = arr / np.abs(arr).max()

    if arr.ndim == 2:
        return arr
    elif color and arr.ndim == 3:
        return arr

    if color:
        img_shape = arr.shape[-3:]
        batch = np.prod(arr.shape[:-3])
        mshape = mosaic_shape(batch)
    else:
        img_shape = arr.shape[-2:]
        batch = np.prod(arr.shape[:-2])
        mshape = mosaic_shape(batch)

    if np.prod(mshape) == batch:
        img = arr.reshape((batch,) + img_shape)
    else:
        img = np.zeros((np.prod(mshape),) + img_shape, dtype=arr.dtype)
        img[:batch, ...] = arr.reshape((batch,) + img_shape)

    img = img.reshape(mshape + img_shape)
    if color:
        img = np.transpose(img, (0, 2, 1, 3, 4))
        img = img.reshape((img_shape[0] * mshape[0], img_shape[1] * mshape[1], 3))
    else:
        img = np.transpose(img, (0, 2, 1, 3))
        img = img.reshape((img_shape[0] * mshape[0], img_shape[1] * mshape[1]))

    return img
