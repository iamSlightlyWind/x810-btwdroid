# X810 GNOME auto-rotation

GNOME obtains tablet orientation through the standard `net.hadess.SensorProxy`
D-Bus API. The stock SM-X810 accelerometer is exposed by Qualcomm's ADSP/SSC,
not by an AP-side IIO device, so the generic Arch `iio-sensor-proxy` exits with
“No sensors or missing kernel drivers”. The X810 package replaces that generic
proxy with the SSC-enabled build and supplies the pinned FastRPC/QRTR services,
udev rules, and GNOME SensorProxy registration.

Startup is deferred until after GDM is available. The service maps Android's
vendor logical partition read-only, mounts vendor/APNHLOS/DSP/persist read-only
(ext4 mounts use `noload`), stages the tablet-local ADSP firmware into the
Arch rootfs, and starts the sensor protection domain once. The only mutable
paths are under the Arch root filesystem and `/run`; no Android partition is
written. The GNOME sensor mount matrix corrects the X810 panel orientation.

With the accelerometer visible to SensorProxy, GNOME's built-in orientation
lock/auto-rotation control is available in Quick Settings. No distro-specific
Tab Companion control or GNOME extension is required.

The firmware remains on the tablet's own APNHLOS partition and is read at boot;
it is not redistributed in the rootfs. ADSP support objects under
`/usr/share/qcom/sm8550/Samsung/gts9wifi/dsp/adsp` are the public runtime
skeletons from the existing Fedora X810 sensor stack. Source pins and fixes are
maintained in the Fedora port's `specs/iio-sensor-proxy-libssc` and
`specs/hexagonrpcd-samsung` trees; this Arch package carries the tested runtime
payload and matching X810 service configuration.

Validation is encoded in `tools/test-x810-sensor-stack.py`. Hardware acceptance
requires `HasAccelerometer=true` from SensorProxy and a physical rotation check
on Windstation; a successful build alone does not claim that the live sensor
is working.
