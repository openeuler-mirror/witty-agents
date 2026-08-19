# xlite-operator-dev

## 用途

根据优化方案，编写或修改 xlite 的 AscendC 算子、C++ 管线、Python 模型适配代码与测试用例。

## 何时使用

- `[xlite-analyzer]` 识别瓶颈并制定方案后。
- 用户明确要求实现某个具体算子/推理逻辑优化时。

## 输入

- 优化方案（来自 analyzer 或用户描述）。
- 相关源码文件路径。
- 精度与性能验收标准。

## 输出

- 修改后的源码文件。
- 新增/更新的测试文件。
- 构建与测试命令。

## 执行步骤

1. **理解现有实现**
   - 阅读目标算子的 kernel header/implementation、`csrc/op.cpp` 中的接口、`csrc/model.cpp` 中的调用链路。
   - 阅读对应的 Python 参考实现（如 `tests/models/qwen3_5.py`）。

2. **设计修改**
   - 明确是新增算子、修改现有算子，还是调整 `ForwardAttnLinear` / `ForwardMLP` 等管线。
   - 确定输入/输出 layout、数据类型、shape 约束。

3. **代码实现**
   - 如果是 AscendC kernel：
     - 新增/修改 `csrc/kernels/<op>_<dtype>.cpp` 与 `csrc/kernels/<op>.h`。
     - 在 `csrc/op.cpp` 中新增 `XliteOp<OpName>` 封装。
     - 在 `csrc/_C.cpp` 中绑定到 Python（如需要）。
   - 如果是管线逻辑：
     - 修改 `csrc/model.cpp` 中对应 `Forward*` 函数。
   - 如果是 Python 适配：
     - 修改 `tests/models/<model>.py` 或 xlite Python 封装。

4. **单算子测试**
   - 新增/更新 `tests/kernels/<op>.py`。
   - 与 PyTorch eager 结果对比，bf16 相对误差 `< 1e-3`。

5. **生成构建命令**
   - 输出类似：
     ```bash
     cmake -B build -S . && cmake --build build -j
     cd tests/kernels && python <op>.py
     ```

## 工具

- `Read` / `Grep` / `Glob`：阅读源码。
- `Write` / `Edit`：修改代码。
- `Bash`：编译与测试。

## 注意事项

- 任何代码修改前，必须先调用 `[xlite-atomic-journal]` 保存 `before.patch`。
- 新增 kernel 必须同时支持 `bfloat16_t` 与 `float16_t`（如原项目已有对应模板）。
- 不得修改 xlite 以外的代码。
