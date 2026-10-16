# -*- coding: utf-8 -*-
# -*- coding: utf-8 -*-
# -*- coding: utf-8 -*-
# run_cv_sweep.py —— 交叉验证对照实验：尺寸 × 增广
#
# 一组组显式调用，避免 shell 循环里参数被切错
import os
import subprocess
import sys

PY = r"D:\AI\python\envs\train\Scripts\python.exe"
PROJ = r"E:\PlantDiseaseProject"
CV = os.path.join(PROJ, "_toolchain", "cv_cls_int8.py")

CONFIGS = [
    (48, True,  '48x48 + 增广'),
    (48, False, '48x48 无增广'),
    (96, True,  '96x96 + 增广'),
    (96, False, '96x96 无增广'),
]

GREP = r'^  (折|全部|唯一)|平衡准确率 |weed 召回|crop 召回|误打作物 |漏打杂草 |真实|crop  +|weed  +|✅'

def main():
    folds = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    epochs = int(sys.argv[2]) if len(sys.argv) > 2 else 40
    env = dict(os.environ)
    for k in ('http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY'):
        env.pop(k, None)

    for sz, aug, label in CONFIGS:
        print('\n' + '#' * 70)
        print(f'########## {label}  (folds={folds} epochs={epochs}) ##########')
        print('#' * 70, flush=True)
        cmd = [PY, CV, '--size', str(sz), '--folds', str(folds),
               '--epochs', str(epochs)]
        if aug:
            cmd.append('--augment')
        # 用 findstr 等价过滤：这里直接全量输出到文件再筛
        r = subprocess.run(cmd, cwd=PROJ, env=env, capture_output=True,
                           text=True, encoding='utf-8', errors='replace')
        for line in (r.stdout or '').splitlines():
            print(line)
        if r.returncode != 0:
            print(f'!! 退出码 {r.returncode}')
            err = (r.stderr or '').splitlines()
            for line in err[-12:]:
                print('   ', line)
        sys.stdout.flush()


if __name__ == '__main__':
    main()