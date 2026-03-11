export function HelpDialog() {
  return (
    <>
      <div className="dialog-header">帮助</div>
      <div className="dialog-body">
        <div className="dialog-section-title">快捷键</div>
        <div className="dialog-row">
          <span className="dialog-row-key">Esc</span>
          <span className="dialog-row-val">关闭对话框</span>
        </div>
        <div className="dialog-row">
          <span className="dialog-row-key">Enter</span>
          <span className="dialog-row-val">发送消息</span>
        </div>
        <div className="dialog-row">
          <span className="dialog-row-key">Shift+Enter</span>
          <span className="dialog-row-val">换行</span>
        </div>

        <div className="dialog-section-title">斜杠命令</div>
        <div className="dialog-row">
          <span className="dialog-row-key">/help</span>
          <span className="dialog-row-val">显示帮助</span>
        </div>
        <div className="dialog-row">
          <span className="dialog-row-key">/ops</span>
          <span className="dialog-row-val">支持的 COMSOL 操作</span>
        </div>
        <div className="dialog-row">
          <span className="dialog-row-key">/run</span>
          <span className="dialog-row-val">默认模式（自然语言 → 模型）</span>
        </div>
        <div className="dialog-row">
          <span className="dialog-row-key">/plan</span>
          <span className="dialog-row-val">计划模式（自然语言 → JSON）</span>
        </div>
        <div className="dialog-row">
          <span className="dialog-row-key">/exec</span>
          <span className="dialog-row-val">根据 JSON 创建模型</span>
        </div>
        <div className="dialog-row">
          <span className="dialog-row-key">/backend</span>
          <span className="dialog-row-val">选择 LLM 后端</span>
        </div>
        <div className="dialog-row">
          <span className="dialog-row-key">/context</span>
          <span className="dialog-row-val">查看或清除对话历史</span>
        </div>
        <div className="dialog-row">
          <span className="dialog-row-key">/output</span>
          <span className="dialog-row-val">设置默认输出文件名</span>
        </div>
        <div className="dialog-row">
          <span className="dialog-row-key">/demo</span>
          <span className="dialog-row-val">演示示例</span>
        </div>
        <div className="dialog-row">
          <span className="dialog-row-key">/doctor</span>
          <span className="dialog-row-val">环境诊断</span>
        </div>
        <div className="dialog-row">
          <span className="dialog-row-key">/exit</span>
          <span className="dialog-row-val">退出</span>
        </div>

        <div className="dialog-section-title">支持能力</div>
        <div className="dialog-row">
          <span className="dialog-row-key">2D/3D 几何</span>
          <span className="dialog-row-val">
            矩形/圆/椭圆/多边形/长方体/圆柱/球/锥/圆环
          </span>
        </div>
        <div className="dialog-row">
          <span className="dialog-row-key">布尔运算</span>
          <span className="dialog-row-val">并集/差集/交集/拉伸/旋转</span>
        </div>
        <div className="dialog-row">
          <span className="dialog-row-key">材料系统</span>
          <span className="dialog-row-val">内置材料库 + 自定义属性</span>
        </div>
        <div className="dialog-row">
          <span className="dialog-row-key">物理场</span>
          <span className="dialog-row-val">
            传热/电磁/结构/流体/声学/压电/化学/多体
          </span>
        </div>
        <div className="dialog-row">
          <span className="dialog-row-key">多物理场耦合</span>
          <span className="dialog-row-val">热应力/流固/电磁热</span>
        </div>
        <div className="dialog-row">
          <span className="dialog-row-key">研究类型</span>
          <span className="dialog-row-val">
            稳态/瞬态/特征值/频域/参数化扫描
          </span>
        </div>

        <div className="dialog-section-title">官方 API 集成（3023 项）</div>
        <div className="dialog-row">
          <span className="dialog-row-key">集成内容</span>
          <span className="dialog-row-val">
            已接入 COMSOL 官方 index-all 方法条目并生成 3023 个包装函数
          </span>
        </div>
        <div className="dialog-row">
          <span className="dialog-row-key">覆盖包</span>
          <span className="dialog-row-val">
            com.comsol.model.* / com.comsol.model.util.* / com.comsol.api.database.*
          </span>
        </div>
        <div className="dialog-row">
          <span className="dialog-row-key">执行链路</span>
          <span className="dialog-row-val">
            /help 展示说明；实际调用走 java_api_controller.py → comsol_runner.py
          </span>
        </div>
        <div className="dialog-row">
          <span className="dialog-row-key">函数命名</span>
          <span className="dialog-row-val">
            api_接口名_方法名（重载自动加序号），例如 api_geomsequence_absrepairtol
          </span>
        </div>
        <div className="dialog-row">
          <span className="dialog-row-key">几何与网格</span>
          <span className="dialog-row-val">
            几何构建、布尔运算、选择集、网格序列、尺寸控制与网格运行
          </span>
        </div>
        <div className="dialog-row">
          <span className="dialog-row-key">物理与求解</span>
          <span className="dialog-row-val">
            物理场特征创建、边界条件、研究步骤、求解流程、参数化扫描
          </span>
        </div>
        <div className="dialog-row">
          <span className="dialog-row-key">后处理与数据</span>
          <span className="dialog-row-val">
            表格列/行写入、结果节点操作、模型管理与数据库相关 API
          </span>
        </div>
        <div className="dialog-row">
          <span className="dialog-row-key">调用模式</span>
          <span className="dialog-row-val">
            支持通用调用（method + target_path）和静态类调用（class + method）
          </span>
        </div>
      </div>
    </>
  );
}
