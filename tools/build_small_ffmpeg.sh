#!/usr/bin/env bash
# Optional: compact Windows encoder. Not required to RUN Nexus or build with stock imageio FFmpeg.
# Linux/WSL prerequisites: gcc/g++-mingw-w64-x86-64, make, nasm, pkg-config, curl, tar.
# All configuration/source information is preserved in build/encoder/ for redistribution.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CACHE="${NEXUS_ENCODER_CACHE:-${XDG_CACHE_HOME:-$HOME/.cache}/nexus-encoder}"
SRC="$CACHE/src"
PREFIX="$CACHE/prefix"
JOBS="${NEXUS_BUILD_JOBS:-6}"
mkdir -p "$SRC" "$PREFIX" "$ROOT/build/encoder"
fetch() { [ -f "$2" ] || curl -fLsS "$1" -o "$2"; }
fetch 'https://code.videolan.org/videolan/x264/-/archive/stable/x264-stable.tar.gz' "$SRC/x264.tar.gz"
fetch 'https://github.com/webmproject/libvpx/archive/refs/tags/v1.15.0.tar.gz' "$SRC/vpx.tar.gz"
fetch 'https://downloads.xiph.org/releases/opus/opus-1.5.2.tar.gz' "$SRC/opus.tar.gz"
fetch 'https://ffmpeg.org/releases/ffmpeg-7.1.5.tar.xz' "$SRC/ffmpeg.tar.xz"
cd "$SRC"
sha256sum x264.tar.gz vpx.tar.gz opus.tar.gz ffmpeg.tar.xz > "$ROOT/build/encoder/source-checksums.txt"
for archive in x264.tar.gz vpx.tar.gz opus.tar.gz ffmpeg.tar.xz; do tar -xf "$archive"; done
export PKG_CONFIG_LIBDIR="$PREFIX/lib/pkgconfig"
export PKG_CONFIG_PATH="$PKG_CONFIG_LIBDIR"
export CROSS=x86_64-w64-mingw32-
cd "$SRC/x264-stable"
./configure --prefix="$PREFIX" --host=x86_64-w64-mingw32 --cross-prefix="$CROSS" \
  --enable-static --disable-cli --disable-opencl --disable-lavf --disable-swscale --enable-strip
make -j"$JOBS"
make install
cd "$SRC/libvpx-1.15.0"
CROSS="$CROSS" ./configure --prefix="$PREFIX" --target=x86_64-win64-gcc \
  --disable-examples --disable-tools --disable-docs --disable-unit-tests --disable-vp9-highbitdepth
make -j"$JOBS"
make install
cd "$SRC/opus-1.5.2"
./configure --prefix="$PREFIX" --host=x86_64-w64-mingw32 --enable-static --disable-shared \
  --disable-doc --disable-extra-programs
make -j"$JOBS"
make install
FFDIR="$(find "$SRC" -maxdepth 1 -type d -name 'ffmpeg-7.1*' | sort | tail -1)"
cd "$FFDIR"
./configure --prefix="$PREFIX" --target-os=mingw32 --arch=x86_64 --cross-prefix="$CROSS" \
  --enable-cross-compile --pkg-config=pkg-config --pkg-config-flags=--static \
  --disable-autodetect --disable-everything --disable-network --disable-doc --disable-debug \
  --disable-ffprobe --disable-ffplay --enable-ffmpeg --enable-small \
  --enable-gpl --enable-version3 --enable-static --disable-shared \
  --enable-libx264 --enable-libvpx --enable-libopus \
  --enable-avcodec --enable-avformat --enable-avfilter --enable-swscale --enable-swresample \
  --enable-protocol=file,pipe \
  --enable-demuxer=rawvideo,wav,mov,matroska \
  --enable-muxer=mp4,matroska,webm,null \
  --enable-encoder=libx264,libvpx_vp8,libvpx_vp9,libopus,aac,mpeg4,ffv1,pcm_s16le,rawvideo,wrapped_avframe \
  --enable-decoder=h264,vp8,vp9,aac,opus,mpeg4,ffv1,pcm_s16le,rawvideo \
  --enable-parser=h264,vp8,vp9,aac,mpeg4video,opus \
  --enable-filter=buffer,buffersink,abuffer,abuffersink,amix,alimiter,aformat,aresample,anull,null,scale,format,fps \
  --extra-cflags="-I$PREFIX/include" --extra-ldflags="-L$PREFIX/lib -static -static-libgcc -static-libstdc++"
make -j"$JOBS"
"${CROSS}strip" ffmpeg.exe
cp ffmpeg.exe "$ROOT/build/encoder/ffmpeg.exe"
cp config.h "$ROOT/build/encoder/config.h"
cp ffbuild/config.mak "$ROOT/build/encoder/config.mak"
cp COPYING.GPLv3 "$ROOT/build/encoder/FFmpeg-LICENSE.txt"
printf '%s\n' 'FFmpeg 7.1.5 + x264 stable + libvpx 1.15.0 + Opus 1.5.2; MinGW-w64 static Windows x64 build.' > "$ROOT/build/encoder/BUILD.txt"
ls -lh "$ROOT/build/encoder/ffmpeg.exe"
