import sys
from functools import partial
from datetime import datetime
import os

import numpy as np
from numpy import fft
from vispy import scene
from vispy.color import get_colormap
from vispy.scene.visuals import ColorBar
from vispy.scene.visuals import Text

# Configure VisPy backend for remote connections
# Check if we're running over SSH (common environment variables)
is_remote = any([
    'SSH_CLIENT' in os.environ,
    'SSH_CONNECTION' in os.environ,
    'SSH_TTY' in os.environ,
    os.environ.get('DISPLAY', '').startswith(':'),  # X11 forwarding
    os.environ.get('ARRAYSHOW_REMOTE', '0') == '1',  # Explicit remote mode
])

def configure_vispy_for_remote():
    """Configure VisPy with aggressive fallbacks for remote display."""
    print("Configuring VisPy for remote display...")
    
    # Set environment variables for software rendering
    os.environ['LIBGL_ALWAYS_SOFTWARE'] = '1'
    os.environ['GALLIUM_DRIVER'] = 'llvmpipe'  # Use software rasterizer
    os.environ['MESA_GL_VERSION_OVERRIDE'] = '3.3COMPAT'
    os.environ['MESA_GLSL_VERSION_OVERRIDE'] = '330'
    
    try:
        from vispy import app, config
        
        # Try different backend configurations
        backends_to_try = [
            ('pyqt5', {'gl': 'gl'}),
            ('pyqt5', {}),
            ('qt', {}),
        ]
        
        for backend, kwargs in backends_to_try:
            try:
                print(f"Trying backend: {backend} with {kwargs}")
                app.use_app(backend, **kwargs)
                print(f"Successfully configured backend: {backend}")
                break
            except Exception as e:
                print(f"Backend {backend} failed: {e}")
                continue
        else:
            print("All backends failed, using default")
            
        # Configure VisPy for minimal OpenGL requirements
        config.gl_debug = False
        config.gl_max_texture_size = 2048  # Reduce texture size
        
        print("VisPy configured for remote display")
        return True
        
    except Exception as e:
        print(f"Failed to configure VisPy: {e}")
        return False

if is_remote:
    print("Remote connection detected - applying remote display configuration...")
    configure_vispy_for_remote()

# Import qmricolors to register custom colormaps
try:
    import qmricolors
    # Test if the colormaps are actually available
    try:
        get_colormap('lipari')
        get_colormap('navia')
        QMRI_AVAILABLE = True
    except (KeyError, Exception):
        QMRI_AVAILABLE = False
        print("qMRI Colors: Warning - colormaps not properly registered, falling back to default colormaps")
except ImportError:
    QMRI_AVAILABLE = False

# --- Import PyQt5 directly ---
try:
    from PyQt5 import QtCore, QtGui, QtWidgets
except ImportError:
    print(
        "Error: This application requires PyQt5. Please install it (`pip install pyqt5`)."
    )
    sys.exit(1)


class ClickableLabel(QtWidgets.QLabel):
    """A QLabel that emits a clicked signal."""

    clicked = QtCore.pyqtSignal()

    def mousePressEvent(self, event):
        self.clicked.emit()
        super().mousePressEvent(event)


class NDArrayViewer(QtWidgets.QMainWindow):
    """
    A high-performance N-dimensional array viewer with fully configurable dimension roles,
    animation playback, and FFT analysis.
    """

    def _create_canvas_with_fallbacks(self):
        """Create VisPy canvas with multiple fallback strategies for remote connections."""
        canvas_configs = [
            # Standard configuration
            {'keys': 'interactive', 'show': False, 'config': 'default'},
            
            # Remote-optimized configurations
            {'keys': 'interactive', 'show': False, 'gl_debug': False, 'config': 'remote_basic'},
            
            # Minimal configuration
            {'show': False, 'size': (800, 600), 'config': 'minimal'},
            
            # Ultra-minimal configuration
            {'show': False, 'config': 'ultra_minimal'},
        ]
        
        for i, config in enumerate(canvas_configs):
            config_name = config.pop('config')
            print(f"Attempting canvas creation with {config_name} configuration...")
            
            try:
                # Set additional environment variables for each attempt
                if i > 0:  # After first attempt, get more aggressive
                    os.environ['LIBGL_ALWAYS_SOFTWARE'] = '1'
                    os.environ['GALLIUM_DRIVER'] = 'llvmpipe'
                    
                if i > 1:  # Even more aggressive
                    os.environ['MESA_GL_VERSION_OVERRIDE'] = '2.1'
                    os.environ['MESA_GLSL_VERSION_OVERRIDE'] = '120'
                    
                canvas = scene.SceneCanvas(**config)
                print(f"✓ Canvas created successfully with {config_name} configuration")
                return canvas
                
            except Exception as e:
                print(f"✗ {config_name} configuration failed: {e}")
                if i == len(canvas_configs) - 1:
                    print("All canvas configurations failed!")
                    raise e
                continue
        
        raise RuntimeError("Failed to create VisPy canvas with any configuration")

    def __init__(self, data, title="N-D Array Viewer"):
        super().__init__()
        self.original_title = title

        # --- 1. Data and State Management ---
        # Convert non-numpy arrays to numpy (e.g. arrays from Julia, .mat files, etc)
        data = np.asarray(data)

        # Check if data is complex
        self.is_complex_data = np.iscomplexobj(data)
        self.complex_view_mode = "magnitude"  # magnitude, phase, real, imag
        
        if self.is_complex_data:
            # Store original complex data
            self.complex_data = data
            # Start with magnitude view
            data = np.abs(data).astype(np.float32)
        else:
            self.complex_data = None
            if data.dtype != np.float32:
                data = data.astype(np.float32)

        if data.ndim < 2:
            raise ValueError(
                f"Input data must have at least 2 dimensions, but got {data.ndim}."
            )

        self.data = data
        self.dims = []
        self.is_playing = False
        self.is_fft_view = False
        self.fft_data = None
        self.fft_dims = None
        
        # Colorbar state
        self.colorbar_visible = True
        self.colorbar = None
        self.colorbar_text_max = None
        self.colorbar_text_min = None
        self.manual_clim = False
        self.clim_min = 0.0
        self.clim_max = 1.0
        
        # Crosshair cursor state
        self.crosshair_enabled = True
        self.crosshair_text = None
        self.mouse_pos = None
        
        self._assign_initial_roles()

        # --- 2. Create Palettes and Styles ---
        self.default_palette = QtWidgets.QApplication.instance().palette()
        self.green_palette = QtGui.QPalette(self.default_palette)
        self.green_palette.setColor(
            QtGui.QPalette.ColorRole.Highlight, QtGui.QColor("#57E079")
        )
        self.view_button_style_active = "background-color: #57E079; color: black; border: 1px solid #3A9; border-radius: 3px;"
        self.view_button_style_inactive = "background-color: #555; color: #ccc; border: 1px solid #666; border-radius: 3px;"

        # --- 3. Create VisPy Canvas ---
        self.canvas = self._create_canvas_with_fallbacks()
        self.view = self.canvas.central_widget.add_view()
        self.canvas.events.key_press.connect(self._on_key_press)
        self.canvas.events.mouse_move.connect(self._on_mouse_move)

        initial_slice_2d = self._get_display_image()
        self.current_colormap = "lipari" if QMRI_AVAILABLE else "grays"
        try:
            initial_cmap = get_colormap(self.current_colormap)
        except Exception:
            # Fallback to grays if initial colormap fails
            self.current_colormap = "grays"
            initial_cmap = get_colormap("grays")
        self.image = scene.visuals.Image(
            initial_slice_2d, cmap=initial_cmap, parent=self.view.scene, clim="auto"
        )
        self.image.transform = scene.transforms.STTransform()
        
        # Create colorbar
        self.colorbar = ColorBar(
            cmap=initial_cmap,
            size=(128, 10),
            parent=self.view.scene,
            clim="auto",
            orientation="right"
        )
        self.colorbar.transform = scene.transforms.STTransform()
        
        # Create text labels for colorbar limits
        self.colorbar_text_max = Text(
            text="1.0",
            color='white',
            font_size=10,
            parent=self.view.scene,
            anchor_x='left',
            anchor_y='bottom'
        )
        
        self.colorbar_text_min = Text(
            text="0.0",
            color='white',
            font_size=10,
            parent=self.view.scene,
            anchor_x='left',
            anchor_y='top'
        )
        
        # Create crosshair cursor text
        self.crosshair_text = Text(
            text="",
            color='yellow',
            font_size=10,
            parent=self.view.scene,
            anchor_x='left',
            anchor_y='top',
            pos=(0.02, 0.95, 0)  # Top-left corner with some margin
        )
        
        self.view.camera = scene.PanZoomCamera(aspect=1)
        self.view.camera.flip = (0, 1, 0)
        self.view.camera.set_range(x=(0, 1), y=(0, 1), margin=0)

        # --- 4. Create PyQt Widgets ---
        playback_container = QtWidgets.QWidget()
        playback_layout = QtWidgets.QHBoxLayout(playback_container)
        playback_layout.setContentsMargins(5, 5, 5, 5)
        self.play_stop_button = QtWidgets.QPushButton("Play")
        self.loop_checkbox = QtWidgets.QCheckBox("Loop")
        self.loop_checkbox.setChecked(True)
        self.autoscale_checkbox = QtWidgets.QCheckBox("Autoscale on Scroll")
        self.fps_spinbox = QtWidgets.QDoubleSpinBox()
        self.fps_spinbox.setDecimals(1)
        self.fps_spinbox.setRange(0.1, 100.0)
        self.fps_spinbox.setValue(10.0)
        self.fps_spinbox.setSuffix(" FPS")
        
        # Complex array controls
        self.complex_view_combo = QtWidgets.QComboBox()
        self.complex_view_combo.addItems(["Magnitude", "Phase", "Real", "Imaginary"])
        self.complex_view_combo.setCurrentText("Magnitude")
        self.complex_view_combo.currentTextChanged.connect(self._on_complex_view_changed)
        
        # Colormap controls
        self.colormap_combo = QtWidgets.QComboBox()
        colormap_options = ["grays", "hot", "viridis", "coolwarm"]
        if QMRI_AVAILABLE:
            colormap_options = ["lipari", "navia"] + colormap_options
        self.colormap_combo.addItems(colormap_options)
        # Set dropdown to match the actual colormap being used
        self.colormap_combo.setCurrentText(self.current_colormap)
        self.colormap_combo.currentTextChanged.connect(self._on_colormap_changed)
        
        # Color limit controls
        self.auto_clim_checkbox = QtWidgets.QCheckBox("Auto")
        self.auto_clim_checkbox.setChecked(True)
        self.auto_clim_checkbox.toggled.connect(self._on_auto_clim_toggled)
        
        self.clim_min_spinbox = QtWidgets.QDoubleSpinBox()
        self.clim_min_spinbox.setRange(-1e6, 1e6)
        self.clim_min_spinbox.setDecimals(3)
        self.clim_min_spinbox.setValue(0.0)
        self.clim_min_spinbox.setEnabled(False)
        self.clim_min_spinbox.valueChanged.connect(self._on_clim_changed)
        
        self.clim_max_spinbox = QtWidgets.QDoubleSpinBox()
        self.clim_max_spinbox.setRange(-1e6, 1e6)
        self.clim_max_spinbox.setDecimals(3)
        self.clim_max_spinbox.setValue(1.0)
        self.clim_max_spinbox.setEnabled(False)
        self.clim_max_spinbox.valueChanged.connect(self._on_clim_changed)
        
        playback_layout.addWidget(self.play_stop_button)
        playback_layout.addWidget(self.loop_checkbox)
        playback_layout.addWidget(self.autoscale_checkbox)
        
        # Add complex controls if data is complex
        if self.is_complex_data:
            playback_layout.addWidget(QtWidgets.QLabel("Complex View:"))
            playback_layout.addWidget(self.complex_view_combo)
        
        # Add colormap controls
        playback_layout.addWidget(QtWidgets.QLabel("Colormap:"))
        playback_layout.addWidget(self.colormap_combo)
        
        # Add color limit controls
        playback_layout.addWidget(QtWidgets.QLabel("Color Limits:"))
        playback_layout.addWidget(self.auto_clim_checkbox)
        playback_layout.addWidget(QtWidgets.QLabel("Min:"))
        playback_layout.addWidget(self.clim_min_spinbox)
        playback_layout.addWidget(QtWidgets.QLabel("Max:"))
        playback_layout.addWidget(self.clim_max_spinbox)
        
        # Add screenshot export button
        self.screenshot_button = QtWidgets.QPushButton("Screenshot")
        self.screenshot_button.clicked.connect(self._export_screenshot)
        
        playback_layout.addStretch()
        playback_layout.addWidget(self.screenshot_button)
        playback_layout.addWidget(QtWidgets.QLabel("Speed:"))
        playback_layout.addWidget(self.fps_spinbox)

        controls_container = QtWidgets.QWidget()
        self.controls_layout = QtWidgets.QGridLayout(controls_container)
        self.sliders = []
        self.view_buttons = []
        self.info_labels = []
        for i, dim in enumerate(self.dims):
            label_widget = QtWidgets.QWidget()
            label_layout = QtWidgets.QHBoxLayout(label_widget)
            label_layout.setContentsMargins(0, 0, 5, 0)
            label_layout.setSpacing(5)
            label_layout.addWidget(QtWidgets.QLabel(f"Dim {i}:"))
            x_button = ClickableLabel("[X]")
            x_button.setFixedSize(20, 20)
            x_button.setAlignment(QtCore.Qt.AlignCenter)
            x_button.clicked.connect(
                partial(self._set_view_dimension_from_button, i, 0)
            )
            y_button = ClickableLabel("[Y]")
            y_button.setFixedSize(20, 20)
            y_button.setAlignment(QtCore.Qt.AlignCenter)
            y_button.clicked.connect(
                partial(self._set_view_dimension_from_button, i, 1)
            )
            g_button = ClickableLabel("[G]")
            g_button.setFixedSize(20, 20)
            g_button.setAlignment(QtCore.Qt.AlignCenter)
            g_button.clicked.connect(partial(self._toggle_grid_dimension, i))
            label_layout.addWidget(x_button)
            label_layout.addWidget(y_button)
            label_layout.addWidget(g_button)
            self.view_buttons.append((x_button, y_button, g_button))
            slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
            slider.setMinimum(0)
            slider.setMaximum(dim["size"] - 1)
            slider.sliderPressed.connect(partial(self._on_slider_pressed, i))
            slider.valueChanged.connect(partial(self._on_slider_moved, i))
            self.sliders.append(slider)
            info_label = QtWidgets.QLabel()
            info_label.setMinimumWidth(80)
            self.info_labels.append(info_label)
            self.controls_layout.addWidget(label_widget, i, 0)
            self.controls_layout.addWidget(slider, i, 1)
            self.controls_layout.addWidget(info_label, i, 2)
        self.controls_layout.setColumnStretch(1, 1)

        # --- 5. Arrange Main Layout ---
        central_widget = QtWidgets.QWidget()
        main_layout = QtWidgets.QVBoxLayout(central_widget)
        main_layout.addWidget(self.canvas.native)
        main_layout.addWidget(playback_container)
        main_layout.addWidget(controls_container)
        self.setCentralWidget(central_widget)
        self.setWindowTitle(self.original_title)
        self.resize(700, 750)

        # --- 6. Setup Timer and Finalize ---
        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self._advance_slice)
        self.play_stop_button.clicked.connect(self._toggle_playback)
        self.fps_spinbox.valueChanged.connect(self._update_timer_interval)
        
        # Initialize colorbar position
        self._update_colorbar_position()
        
        self._update_view()

    @property
    def active_data(self):
        if self.is_fft_view:
            return self.fft_data
        elif self.is_complex_data:
            return self._get_complex_view_data()
        else:
            return self.data
    
    def _get_complex_view_data(self):
        """Get the appropriate view of complex data based on current mode."""
        if not self.is_complex_data or self.complex_data is None:
            return self.data
            
        if self.complex_view_mode == "magnitude":
            return np.abs(self.complex_data).astype(np.float32)
        elif self.complex_view_mode == "phase":
            return np.angle(self.complex_data).astype(np.float32)
        elif self.complex_view_mode == "real":
            return np.real(self.complex_data).astype(np.float32)
        elif self.complex_view_mode == "imag":
            return np.imag(self.complex_data).astype(np.float32)
        else:
            return np.abs(self.complex_data).astype(np.float32)
    
    def _on_complex_view_changed(self, text):
        """Handle complex view mode changes from dropdown."""
        mode_map = {
            "Magnitude": "magnitude",
            "Phase": "phase",
            "Real": "real",
            "Imaginary": "imag"
        }
        self.complex_view_mode = mode_map.get(text, "magnitude")
        self.data = self._get_complex_view_data()
        self.image.clim = "auto"
        self._update_view()
    
    def _cycle_complex_view(self):
        """Cycle through complex view modes with 'c' key."""
        if not self.is_complex_data:
            return
            
        modes = ["magnitude", "phase", "real", "imag"]
        current_idx = modes.index(self.complex_view_mode)
        next_idx = (current_idx + 1) % len(modes)
        self.complex_view_mode = modes[next_idx]
        
        # Update dropdown to match
        mode_names = ["Magnitude", "Phase", "Real", "Imaginary"]
        self.complex_view_combo.setCurrentText(mode_names[next_idx])
        
        self.data = self._get_complex_view_data()
        self.image.clim = "auto"
        self._update_view()
    
    def _on_colormap_changed(self, text):
        """Handle colormap changes from dropdown."""
        try:
            self.current_colormap = text.lower()
            new_cmap = get_colormap(self.current_colormap)
            
            # Apply to image first
            self.image.cmap = new_cmap
            self.image.update()
            
            # Apply to colorbar separately with extra error handling
            if self.colorbar:
                try:
                    self.colorbar.cmap = new_cmap
                    self.colorbar.update()
                except Exception as colorbar_error:
                    print(f"Warning: Could not update colorbar with '{text}': {colorbar_error}")
                    # Try refreshing the colorbar completely
                    try:
                        self.colorbar.cmap = new_cmap
                        # Force a complete refresh
                        self.colorbar.update()
                        # Also try updating the colorbar text
                        self._update_colorbar_text()
                    except Exception as refresh_error:
                        print(f"Warning: Colorbar refresh failed: {refresh_error}")
                        
        except Exception as e:
            print(f"Warning: Could not set colormap '{text}': {e}")
            # Fallback to grays if colormap fails
            try:
                self.current_colormap = "grays"
                fallback_cmap = get_colormap("grays")
                self.image.cmap = fallback_cmap
                if self.colorbar:
                    self.colorbar.cmap = fallback_cmap
                self.image.update()
                if self.colorbar:
                    self.colorbar.update()
            except Exception:
                pass

    def _toggle_colorbar(self):
        """Toggle colorbar visibility with 'b' key."""
        if self.colorbar:
            self.colorbar_visible = not self.colorbar_visible
            self.colorbar.visible = self.colorbar_visible
            if self.colorbar_text_max:
                self.colorbar_text_max.visible = self.colorbar_visible
            if self.colorbar_text_min:
                self.colorbar_text_min.visible = self.colorbar_visible
            self._update_colorbar_position()

    def _on_auto_clim_toggled(self, checked):
        """Handle auto color limit checkbox toggle."""
        self.manual_clim = not checked
        self.clim_min_spinbox.setEnabled(not checked)
        self.clim_max_spinbox.setEnabled(not checked)
        if not checked:
            # When switching to manual, set spinboxes to current limits
            if hasattr(self.image, 'clim') and self.image.clim is not None:
                if isinstance(self.image.clim, str) and self.image.clim == "auto":
                    # Get actual data range for auto mode
                    data = self._get_display_image()
                    if data.size > 0:
                        self.clim_min = float(np.nanmin(data))
                        self.clim_max = float(np.nanmax(data))
                else:
                    self.clim_min = float(self.image.clim[0])
                    self.clim_max = float(self.image.clim[1])
                
                self.clim_min_spinbox.setValue(self.clim_min)
                self.clim_max_spinbox.setValue(self.clim_max)
        self._update_color_limits()

    def _on_clim_changed(self):
        """Handle manual color limit changes."""
        if self.manual_clim:
            self.clim_min = self.clim_min_spinbox.value()
            self.clim_max = self.clim_max_spinbox.value()
            self._update_color_limits()

    def _update_color_limits(self):
        """Update image and colorbar color limits."""
        if self.manual_clim:
            clim = (self.clim_min, self.clim_max)
            self.image.clim = clim
            if self.colorbar:
                self.colorbar.clim = clim
        else:
            self.image.clim = "auto"
            if self.colorbar:
                self.colorbar.clim = "auto"
                
        # Update text labels with current limits
        self._update_colorbar_text()
        
        self.image.update()
        if self.colorbar:
            self.colorbar.update()

    def _update_colorbar_text(self):
        """Update colorbar text labels with current limits."""
        if not self.colorbar_text_max or not self.colorbar_text_min:
            return
            
        # Get current color limits
        if self.manual_clim:
            clim_min = self.clim_min
            clim_max = self.clim_max
        else:
            # For auto mode, try to get actual limits from image
            if hasattr(self.image, '_data') and self.image._data is not None:
                clim_min = float(np.nanmin(self.image._data))
                clim_max = float(np.nanmax(self.image._data))
            else:
                clim_min = 0.0
                clim_max = 1.0
        
        # Update text content
        self.colorbar_text_max.text = f"{clim_max:.2f}"
        self.colorbar_text_min.text = f"{clim_min:.2f}"

    def _on_mouse_move(self, event):
        """Handle mouse movement for crosshair cursor."""
        if not self.crosshair_enabled or not self.crosshair_text:
            self.crosshair_text.text = ""
            return
            
        try:
            # Get mouse position in canvas coordinates
            mouse_pos = event.pos
            
            # Get the actual data being displayed (respects FFT/complex modes)
            display_data = self.active_data
            
            # Get current 2D slice from the active data
            view_indices = self._get_view_indices()
            display_slice = display_data[view_indices]
            h, w = display_slice.shape
            
            # Get canvas size to normalize mouse position
            canvas_size = self.canvas.size
            
            # The image fills the canvas area, accounting for aspect ratio preservation
            # The camera is set to (0,1) range, so normalize accordingly
            norm_x = mouse_pos[0] / canvas_size[0]
            norm_y = mouse_pos[1] / canvas_size[1]
            
            # Map to pixel coordinates (flip Y because canvas Y goes down, image Y goes up)
            img_x = int(norm_x * w)
            img_y = int((1.0 - norm_y) * h)  # Flip Y coordinate
            
            # Check bounds and get pixel value from the actual displayed data
            if 0 <= img_x < w and 0 <= img_y < h:
                pixel_value = display_slice[img_y, img_x]
                self.crosshair_text.text = f"({img_x}, {img_y}): {pixel_value:.3f}"
                self.crosshair_text.visible = True
            else:
                self.crosshair_text.text = ""
                
        except Exception as e:
            # Clear text on error
            self.crosshair_text.text = ""

    def _toggle_crosshair(self):
        """Toggle crosshair cursor visibility with 'x' key."""
        self.crosshair_enabled = not self.crosshair_enabled
        if not self.crosshair_enabled:
            self.crosshair_text.text = ""
        else:
            self.crosshair_text.text = "Crosshair enabled - move mouse over image"

    def _get_view_indices(self):
        """Get the indices for the current 2D slice being displayed."""
        # Build slice indices for all dimensions
        indices = []
        for dim in self.dims:
            if dim["role"] in ["view_x", "view_y"]:
                indices.append(slice(None))  # Full slice for view dimensions
            else:
                indices.append(dim["index"])  # Fixed index for other dimensions
        return tuple(indices)

    def _export_screenshot(self):
        """Export the current view as a screenshot."""
        try:
            # Generate filename with timestamp
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"arrayshow_screenshot_{timestamp}.png"
            
            # Get screenshot from canvas
            img = self.canvas.render()
            
            # Use QtWidgets file dialog for save location
            from PyQt5.QtWidgets import QFileDialog
            
            filepath, _ = QFileDialog.getSaveFileName(
                self,
                "Save Screenshot",
                filename,
                "PNG Files (*.png);;All Files (*)"
            )
            
            if filepath:
                # Save the image using VisPy's built-in method
                try:
                    if hasattr(img, 'write_png'):
                        img.write_png(filepath)
                    else:
                        # Alternative: use PIL if available
                        from PIL import Image
                        if hasattr(img, 'copy'):
                            pil_img = Image.fromarray(img)
                            pil_img.save(filepath)
                        else:
                            # Last resort: create image from array
                            import numpy as np
                            img_array = np.asarray(img)
                            pil_img = Image.fromarray(img_array)
                            pil_img.save(filepath)
                    
                    print(f"Screenshot saved to: {filepath}")
                except Exception as e:
                    print(f"Error with image format: {e}")
                    # Try saving raw canvas data
                    try:
                        # Get QWidget and save as pixmap
                        pixmap = self.canvas.native.grab()
                        pixmap.save(filepath)
                        print(f"Screenshot saved to: {filepath}")
                    except Exception as e2:
                        print(f"Error saving with pixmap: {e2}")
                
        except Exception as e:
            print(f"Error saving screenshot: {e}")

    def _update_colorbar_position(self):
        """Update colorbar position relative to the image."""
        if not self.colorbar or not self.colorbar_visible:
            return
        
        # Position the colorbar
        colorbar_x = 1.05
        colorbar_y = 0.5
        self.colorbar.transform.translate = (colorbar_x, colorbar_y, 0)
        self.colorbar.transform.scale = (0.003, 0.008, 1)
        
        # Position the text labels at the exact top and bottom of colorbar
        if self.colorbar_text_max:
            # Max value at top of colorbar (100% height)
            self.colorbar_text_max.pos = (colorbar_x + 0.03, colorbar_y - 0.52, 0)
            
        if self.colorbar_text_min:
            # Min value at bottom of colorbar (0% height)
            self.colorbar_text_min.pos = (colorbar_x + 0.03, colorbar_y + 0.52, 0)

    def _assign_initial_roles(self):
        self.dims.clear()
        for i, size in enumerate(self.data.shape):
            role = "fixed"
            if i == 0:
                role = "view_x"
            elif i == 1:
                role = "view_y"
            elif i == 2 and self.data.ndim > 2:
                role = "scroll"
            self.dims.append({"role": role, "index": size // 2, "size": size})
        self._update_scroll_dim_index()

    def _get_display_image(self):
        grid_dim_idx = next(
            (i for i, d in enumerate(self.dims) if d["role"] == "view_grid"), None
        )
        if grid_dim_idx is None:
            return self._get_single_slice()
        else:
            return self._build_grid_image(grid_dim_idx)

    def _get_single_slice(self, slicer_override=None):
        slicer = slicer_override or [
            slice(None) if "view" in d["role"] else d["index"] for d in self.dims
        ]
        x_dim_idx = next(i for i, d in enumerate(self.dims) if d["role"] == "view_x")
        y_dim_idx = next(i for i, d in enumerate(self.dims) if d["role"] == "view_y")
        slice_data = self.active_data[tuple(slicer)]
        if y_dim_idx < x_dim_idx:
            slice_data = slice_data.T
        return slice_data

    def _calculate_grid_layout(self, num_images):
        if num_images == 0:
            return 0, 0
        best_rows = 1
        for r in range(int(np.sqrt(num_images)), 0, -1):
            if num_images % r == 0:
                best_rows = r
                break
        return best_rows, num_images // best_rows

    def _build_grid_image(self, grid_dim_idx):
        grid_dim = self.dims[grid_dim_idx]
        num_images = grid_dim["size"]
        slicer = [slice(None) if "view" in d["role"] else d["index"] for d in self.dims]
        slicer[grid_dim_idx] = 0
        template_slice = self._get_single_slice(slicer)
        slice_h, slice_w = template_slice.shape
        rows, cols = self._calculate_grid_layout(num_images)
        grid_image = np.zeros(
            (rows * slice_h, cols * slice_w), dtype=self.active_data.dtype
        )
        for i in range(num_images):
            slicer[grid_dim_idx] = i
            current_slice = self._get_single_slice(slicer)
            r, c = i // cols, i % cols
            grid_image[
                r * slice_h : (r + 1) * slice_h, c * slice_w : (c + 1) * slice_w
            ] = current_slice
        return grid_image

    def _reassign_scroll_and_fixed(self):
        found_scroll = False
        for dim in self.dims:
            if "view" not in dim["role"]:
                if not found_scroll:
                    dim["role"] = "scroll"
                    found_scroll = True
                else:
                    dim["role"] = "fixed"
        self._update_scroll_dim_index()

    def _reassign_all_roles(self, x_idx, y_idx):
        if self.is_playing:
            self._toggle_playback()
        for i, dim in enumerate(self.dims):
            if i == x_idx:
                dim["role"] = "view_x"
            elif i == y_idx:
                dim["role"] = "view_y"
            else:
                dim["role"] = "fixed"
        self._reassign_scroll_and_fixed()
        self.image.clim = "auto"
        self._update_view()

    def _set_view_dimension_from_button(self, new_dim_idx, axis):
        current_x_idx = next(
            i for i, d in enumerate(self.dims) if d["role"] == "view_x"
        )
        current_y_idx = next(
            i for i, d in enumerate(self.dims) if d["role"] == "view_y"
        )
        if (axis == 0 and new_dim_idx == current_y_idx) or (
            axis == 1 and new_dim_idx == current_x_idx
        ):
            self._reassign_all_roles(current_y_idx, current_x_idx)
        else:
            if axis == 0:
                self._reassign_all_roles(new_dim_idx, current_y_idx)
            else:
                self._reassign_all_roles(current_x_idx, new_dim_idx)

    def _toggle_grid_dimension(self, dim_idx):
        if self.is_playing:
            self._toggle_playback()
        current_role = self.dims[dim_idx]["role"]
        if current_role == "view_grid":
            self.dims[dim_idx]["role"] = "scroll"
            self._reassign_scroll_and_fixed()
        elif "view" not in current_role:
            for d in self.dims:
                if d["role"] == "view_grid":
                    d["role"] = "fixed"
            self.dims[dim_idx]["role"] = "view_grid"
            self._reassign_scroll_and_fixed()
        self.image.clim = "auto"
        self._update_view()

    def _prompt_for_view_dims(self):
        if self.is_playing:
            self._toggle_playback()
        current_x = next(i for i, d in enumerate(self.dims) if d["role"] == "view_x")
        current_y = next(i for i, d in enumerate(self.dims) if d["role"] == "view_y")
        prompt_text = f"Enter two different dimension indices (0-{self.data.ndim - 1}) separated by a space.\nCurrent is X={current_x}, Y={current_y}."
        text, ok = QtWidgets.QInputDialog.getText(
            self, "Set View Dimensions", prompt_text
        )
        if not (ok and text):
            return
        try:
            parts = text.split()
            if len(parts) != 2:
                raise ValueError("Please enter exactly two numbers.")
            x_dim, y_dim = int(parts[0]), int(parts[1])
            if not (0 <= x_dim < self.data.ndim and 0 <= y_dim < self.data.ndim):
                raise ValueError(
                    f"Dimensions must be between 0 and {self.data.ndim - 1}."
                )
            if x_dim == y_dim:
                raise ValueError("The two dimensions must be different.")
            self._reassign_all_roles(x_dim, y_dim)
        except ValueError as e:
            QtWidgets.QMessageBox.warning(self, "Invalid Input", str(e))

    def _update_scroll_dim_index(self):
        self.scroll_dim_idx = next(
            (i for i, d in enumerate(self.dims) if d["role"] == "scroll"), -1
        )

    def _set_scroll_dimension(self, new_scroll_idx):
        if self.is_playing:
            self._toggle_playback()
        if "view" in self.dims[new_scroll_idx]["role"]:
            return
        old_scroll_idx = self.scroll_dim_idx
        if old_scroll_idx == new_scroll_idx:
            return
        if old_scroll_idx != -1:
            self.dims[old_scroll_idx]["role"] = "fixed"
        self.dims[new_scroll_idx]["role"] = "scroll"
        self._update_scroll_dim_index()
        self._update_view()

    def _change_scroll_dimension_by_cycle(self, direction):
        if self.is_playing:
            self._toggle_playback()
        cyclable_dims = [
            (i, d) for i, d in enumerate(self.dims) if "view" not in d["role"]
        ]
        if len(cyclable_dims) < 2:
            return
        cyclable_indices = [i for i, d in cyclable_dims]
        try:
            current_pos = cyclable_indices.index(self.scroll_dim_idx)
            new_pos = (current_pos + (1 if direction == "next" else -1)) % len(
                cyclable_indices
            )
            self._set_scroll_dimension(cyclable_indices[new_pos])
        except ValueError:
            self._set_scroll_dimension(cyclable_indices[0])

    def _on_key_press(self, event):
        if event.key in ("j", "k", "l", "h", "v", "g", "f", "c", "b", "x"):
            if self.is_playing:
                self._toggle_playback()

        if self.scroll_dim_idx != -1 and event.key in ("j", "k"):
            current_val = self.dims[self.scroll_dim_idx]["index"]
            if event.key == "j":
                max_val = self.dims[self.scroll_dim_idx]["size"] - 1
                self.dims[self.scroll_dim_idx]["index"] = min(max_val, current_val + 1)
            else:
                self.dims[self.scroll_dim_idx]["index"] = max(0, current_val - 1)
            self._update_view()
        elif event.key == "l":
            self._change_scroll_dimension_by_cycle("next")
        elif event.key == "h":
            self._change_scroll_dimension_by_cycle("prev")
        elif event.key == "v":
            self._prompt_for_view_dims()
        elif event.key == "g":
            grid_dim_idx = next(
                (i for i, d in enumerate(self.dims) if d["role"] == "view_grid"), None
            )
            if grid_dim_idx is not None:
                self._toggle_grid_dimension(grid_dim_idx)
            elif self.scroll_dim_idx != -1:
                self._toggle_grid_dimension(self.scroll_dim_idx)
        elif event.key == "f":
            self._toggle_fft_view()
        elif event.key == "c":
            self._cycle_complex_view()
        elif event.key == "b":
            self._toggle_colorbar()
        elif event.key == "x":
            self._toggle_crosshair()

    def _on_slider_pressed(self, dim_idx):
        if self.is_playing:
            self._toggle_playback()
        if self.dims[dim_idx]["role"] == "fixed":
            self._set_scroll_dimension(dim_idx)

    def _on_slider_moved(self, dim_idx, value):
        if self.is_playing:
            self._toggle_playback()
        if "view" not in self.dims[dim_idx]["role"]:
            self.dims[dim_idx]["index"] = value
            self._update_view()

    def _update_ui_state(self):
        if self.is_fft_view:
            self.setWindowTitle(
                f"{self.original_title} - FFT View (dims: {self.fft_dims})"
            )
        elif self.is_complex_data:
            self.setWindowTitle(
                f"{self.original_title} - Complex View ({self.complex_view_mode.capitalize()})"
            )
        else:
            self.setWindowTitle(self.original_title)

        for i, dim in enumerate(self.dims):
            slider = self.sliders[i]
            x_button, y_button, g_button = self.view_buttons[i]
            info_label = self.info_labels[i]
            slider.blockSignals(True)
            slider.setValue(dim["index"])
            slider.blockSignals(False)
            is_view = "view" in dim["role"]
            slider.setEnabled(not is_view)
            x_button.setStyleSheet(
                self.view_button_style_active
                if dim["role"] == "view_x"
                else self.view_button_style_inactive
            )
            y_button.setStyleSheet(
                self.view_button_style_active
                if dim["role"] == "view_y"
                else self.view_button_style_inactive
            )
            g_button.setStyleSheet(
                self.view_button_style_active
                if dim["role"] == "view_grid"
                else self.view_button_style_inactive
            )
            if dim["role"] == "scroll":
                slider.setPalette(self.green_palette)
            else:
                slider.setPalette(self.default_palette)
            if is_view:
                info_label.setText(f": / {dim['size']}")
            else:
                info_label.setText(f"{dim['index'] + 1} / {dim['size']}")

    def _update_view(self):
        """Central function to update the rendered image and all UI components."""
        display_image = self._get_display_image()
        h, w = display_image.shape
        if h > 0 and w > 0:
            self.image.transform.scale = (1 / w, 1 / h, 1)

        self.image.set_data(display_image)

        # Handle color limits based on auto/manual mode and autoscale setting
        if not self.manual_clim and self.autoscale_checkbox.isChecked():
            self.image.clim = "auto"
            if self.colorbar:
                self.colorbar.clim = "auto"
        elif self.manual_clim:
            # Use manual color limits
            self._update_color_limits()
        
        # Update colorbar position and text
        self._update_colorbar_position()
        self._update_colorbar_text()

        # **FIX:** Explicitly tell VisPy to redraw the canvas.
        # This was previously only happening implicitly when clim was set.
        self.image.update()
        if self.colorbar:
            self.colorbar.update()

        self._update_ui_state()

    # --- Playback Methods ---
    def _toggle_playback(self):
        self.is_playing = not self.is_playing
        if self.is_playing:
            if self.scroll_dim_idx == -1:
                self.is_playing = False
                return
            self._update_timer_interval()
            self.timer.start()
            self.play_stop_button.setText("Stop")
        else:
            self.timer.stop()
            self.play_stop_button.setText("Play")

    def _update_timer_interval(self):
        fps = self.fps_spinbox.value()
        if fps > 0:
            self.timer.setInterval(int(1000 / fps))

    def _advance_slice(self):
        if self.scroll_dim_idx == -1:
            self._toggle_playback()
            return

        scroll_dim = self.dims[self.scroll_dim_idx]
        current_index = scroll_dim["index"]
        max_index = scroll_dim["size"] - 1
        new_index = current_index + 1

        if new_index > max_index:
            if self.loop_checkbox.isChecked():
                new_index = 0
            else:
                self._toggle_playback()
                return

        scroll_dim["index"] = new_index
        self._update_view()

    # --- FFT Methods ---
    def _toggle_fft_view(self):
        if self.is_fft_view:
            self.is_fft_view = False
            self.fft_data = None
            self.fft_dims = None
        else:
            self._prompt_for_fft_dims()
            if not self.is_fft_view:
                return

        self.image.clim = "auto"
        self._update_view()

    def _prompt_for_fft_dims(self):
        prompt_text = f"Enter dimension indices (0-{self.data.ndim - 1}) for FFT, separated by spaces."
        text, ok = QtWidgets.QInputDialog.getText(
            self, "Set FFT Dimensions", prompt_text
        )
        if not (ok and text):
            return

        try:
            parts = text.split()
            if not parts:
                raise ValueError("Please enter at least one dimension.")
            dims_to_fft = sorted(list(set([int(p) for p in parts])))
            for d in dims_to_fft:
                if not (0 <= d < self.data.ndim):
                    raise ValueError(
                        f"Dimension {d} is out of range (0-{self.data.ndim - 1})."
                    )
            self._compute_fft(dims_to_fft)
            self.is_fft_view = True
            self.fft_dims = dims_to_fft
        except ValueError as e:
            QtWidgets.QMessageBox.warning(self, "Invalid Input", str(e))
            self.is_fft_view = False

    def _compute_fft(self, dims_to_fft):
        print(f"Computing FFT on dimensions: {dims_to_fft}...")
        fft_result = fft.fftn(self.data, axes=dims_to_fft)
        shifted_fft = fft.fftshift(fft_result, axes=dims_to_fft)
        magnitude = np.abs(shifted_fft)
        log_magnitude = np.log1p(magnitude)
        self.fft_data = log_magnitude.astype(np.float32)
        print("FFT computation complete.")
