# distro.sh - sourced by the other scripts: install hints for the packages they need.
# Only CachyOS (Arch) has been tested; the other package names are best-effort.
#
#   pkg_hint wine|unshield|gamescope|gstreamer|build|glidebuild|tk|zstd   -> prints an install command

distro_family() {
  local id="" like=""
  if [ -r /etc/os-release ]; then
    id="$(. /etc/os-release; echo "${ID:-}")"
    like="$(. /etc/os-release; echo "${ID_LIKE:-}")"
  fi
  case " $id $like " in
    *" arch "*)                      echo arch ;;
    *" debian "*|*" ubuntu "*)       echo debian ;;
    *" fedora "*|*" rhel "*)         echo fedora ;;
    *" suse "*|*" opensuse "*)       echo suse ;;
    *)                               echo unknown ;;
  esac
}

pkg_hint() {
  local fam; fam="$(distro_family)"
  case "$fam:$1" in
    arch:wine)        echo "sudo pacman -S wine" ;;
    arch:unshield)    echo "sudo pacman -S unshield" ;;
    arch:gamescope)   echo "sudo pacman -S gamescope" ;;
    arch:gstreamer)   echo "sudo pacman -S gst-plugins-base gst-plugins-good gst-libav lib32-gst-plugins-base lib32-gst-plugins-good" ;;
    arch:build)       echo "sudo pacman -S --needed git base-devel zlib" ;;
    arch:glidebuild) echo "sudo pacman -S --needed clang lld llvm python" ;;
    arch:tk)          echo "sudo pacman -S tk" ;;
    arch:zstd)        echo "sudo pacman -S zstd" ;;
    debian:wine)      echo "sudo dpkg --add-architecture i386 && sudo apt update && sudo apt install wine wine32:i386" ;;
    debian:unshield)  echo "sudo apt install unshield" ;;
    debian:gamescope) echo "sudo apt install gamescope   (newer releases only)" ;;
    debian:gstreamer) echo "sudo apt install gstreamer1.0-plugins-base gstreamer1.0-plugins-good gstreamer1.0-libav gstreamer1.0-plugins-base:i386 gstreamer1.0-plugins-good:i386" ;;
    debian:build)     echo "sudo apt install git build-essential zlib1g-dev" ;;
    debian:glidebuild) echo "sudo apt install clang lld llvm python3" ;;
    debian:tk)          echo "sudo apt install python3-tk" ;;
    debian:zstd)        echo "sudo apt install zstd" ;;
    fedora:wine)      echo "sudo dnf install wine" ;;
    fedora:unshield)  echo "sudo dnf install unshield" ;;
    fedora:gamescope) echo "sudo dnf install gamescope" ;;
    fedora:gstreamer) echo "sudo dnf install gstreamer1-plugins-base gstreamer1-plugins-good gstreamer1-plugin-libav" ;;
    fedora:build)     echo "sudo dnf install git gcc-c++ make zlib-devel" ;;
    fedora:glidebuild) echo "sudo dnf install clang lld llvm python3" ;;
    fedora:tk)          echo "sudo dnf install python3-tkinter" ;;
    fedora:zstd)        echo "sudo dnf install zstd" ;;
    suse:wine)        echo "sudo zypper install wine" ;;
    suse:unshield)    echo "sudo zypper install unshield" ;;
    suse:gamescope)   echo "sudo zypper install gamescope" ;;
    suse:gstreamer)   echo "sudo zypper install gstreamer-plugins-base gstreamer-plugins-good gstreamer-plugins-libav" ;;
    suse:build)       echo "sudo zypper install git gcc-c++ make zlib-devel" ;;
    suse:glidebuild) echo "sudo zypper install clang lld llvm python3" ;;
    suse:tk)          echo "sudo zypper install python3-tk" ;;
    suse:zstd)        echo "sudo zypper install zstd" ;;
    *)                echo "install '$1' with your distribution's package manager" ;;
  esac
}
