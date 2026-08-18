import platform
import cpuinfo


class InstructScanService:
    @staticmethod
    def check_avx512_support():
        """
        检测当前系统是否支持 AVX-512 指令集

        返回值:
            True: 明确支持 AVX-512
            False: 明确不支持 AVX-512
            "Maybe": 无法确定是否支持
        """
        try:
            # 当前环境为arm则返回 True
            machine = platform.machine().lower()
            if machine.startswith('arm') or machine.startswith('aarch64'):
                return True
            # 优先使用 cpuinfo 库获取精确信息
            info = cpuinfo.get_cpu_info()
            flags = info.get('flags', [])

            # 检查常见的 AVX-512 子指令集
            avx512_flags = [
                'avx512f', 'avx512cd', 'avx512er', 'avx512pf',
                'avx512dq', 'avx512bw', 'avx512vl', 'avx512ifma',
                'avx512vbmi'
            ]

            # 只要存在一个 AVX-512 相关标志即判定支持
            if any(flag in flags for flag in avx512_flags):
                return True

            # 对于 Intel 处理器，检查是否属于已知支持 AVX-512 的系列
            brand = info.get('brand_raw', '').lower()
            if 'intel' in brand:
                # 检查是否为 Xeon 或第 10 代及以后的 Core 处理器
                if 'xeon' in brand or ('core' in brand and any(f' {gen}th' in brand for gen in range(10, 14))):
                    return "Maybe"  # 部分型号支持，需手动确认

            return False

        except Exception as e:
            # 回退到基于平台的检测方法（准确性较低）
            return InstructScanService._fallback_check()

    @staticmethod
    def _fallback_check():
        """
        回退到基于平台命令的检测方法（原实现）
        """
        machine = platform.machine().lower()
        if machine.startswith('arm') or machine.startswith('aarch64'):
            return True
        system = platform.system()

        if system == "Linux":
            try:
                with open('/proc/cpuinfo', 'r') as f:
                    cpuinfo = f.read()
                avx512_flags = [
                    'avx512f', 'avx512cd', 'avx512er', 'avx512pf',
                    'avx512dq', 'avx512bw', 'avx512vl', 'avx512ifma',
                    'avx512vbmi'
                ]
                for flag in avx512_flags:
                    if flag in cpuinfo:
                        return True
                return False
            except Exception:
                return False

        elif system == "Windows":
            try:
                import subprocess
                # 尝试使用 PowerShell 获取更准确的信息
                try:
                    output = subprocess.check_output(
                        "powershell -command \"Get-WmiObject -Class Win32_Processor | Select-Object -ExpandProperty Name\"",
                        shell=True, stderr=subprocess.DEVNULL).decode().lower()
                except:
                    # 旧版 Windows 回退到 wmic
                    output = subprocess.check_output(
                        "wmic cpu get name", shell=True).decode().lower()

                if "avx-512" in output:
                    return True

                # 检查是否为可能支持 AVX-512 的处理器系列
                if "xeon" in output or "i9" in output or "i7" in output:
                    return "Maybe"

                return False
            except Exception:
                return False

        elif system == "Darwin":  # macOS
            # macOS 硬件目前不支持 AVX-512
            return False

        else:
            return False
