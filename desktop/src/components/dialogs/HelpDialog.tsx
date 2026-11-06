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

        <div className="dialog-section-title">扩展功能</div>
        <div className="dialog-row">
          <span className="dialog-row-key">帮助</span>
          <span className="dialog-row-val">打开帮助面板</span>
        </div>
        <div className="dialog-row">
          <span className="dialog-row-key">切换到探讨</span>
          <span className="dialog-row-val">切换到 Discuss 模式，与 LLM 理清需求</span>
        </div>
        <div className="dialog-row">
          <span className="dialog-row-key">切换到执行</span>
          <span className="dialog-row-val">切换到执行模式（执行已确认计划）</span>
        </div>
        <div className="dialog-row">
          <span className="dialog-row-key">切换到规划</span>
          <span className="dialog-row-val">切换到规划模式（基于讨论卡生成计划）</span>
        </div>
        <div className="dialog-row">
          <span className="dialog-row-key">读取 .mph 案例</span>
          <span className="dialog-row-val">选择 mph 文件并生成结构化操作案例</span>
        </div>
        <div className="dialog-row">
          <span className="dialog-row-key">JSON 执行</span>
          <span className="dialog-row-val">根据 JSON 创建模型</span>
        </div>
        <div className="dialog-row">
          <span className="dialog-row-key">LLM 后端</span>
          <span className="dialog-row-val">选择 LLM 后端</span>
        </div>
        <div className="dialog-row">
          <span className="dialog-row-key">上下文</span>
          <span className="dialog-row-val">查看或清除对话历史</span>
        </div>
        <div className="dialog-row">
          <span className="dialog-row-key">输出设置</span>
          <span className="dialog-row-val">设置默认输出文件名</span>
        </div>
        <div className="dialog-row">
          <span className="dialog-row-key">牛顿环示例</span>
          <span className="dialog-row-val">触发内置牛顿环等厚干涉仿真案例</span>
        </div>
        <div className="dialog-row">
          <span className="dialog-row-key">环境诊断</span>
          <span className="dialog-row-val">环境诊断</span>
        </div>
        <div className="dialog-row">
          <span className="dialog-row-key">退出程序</span>
          <span className="dialog-row-val">退出</span>
        </div>

        <div className="dialog-section-title">支持能力</div>
        <div className="dialog-row">
          <span className="dialog-row-key">牛顿环几何</span>
          <span className="dialog-row-val">
            平凸透镜、平板/平面镜、空气薄膜、轴对称环形观察面
          </span>
        </div>
        <div className="dialog-row">
          <span className="dialog-row-key">光学过程</span>
          <span className="dialog-row-val">反射、透射、相位反转、Fresnel 损耗与可选吸收损耗</span>
        </div>
        <div className="dialog-row">
          <span className="dialog-row-key">单色光扫描</span>
          <span className="dialog-row-val">486.1 nm / 546.1 nm / 589.3 nm / 632.8 nm</span>
        </div>
        <div className="dialog-row">
          <span className="dialog-row-key">解析校验</span>
          <span className="dialog-row-val">用反射暗环半径关系 r_m = sqrt(m R lambda) 校验前几级环</span>
        </div>
        <div className="dialog-row">
          <span className="dialog-row-key">结果导出</span>
          <span className="dialog-row-val">导出四种波长下的牛顿环图像和汇总 CSV</span>
        </div>
        <div className="dialog-row">
          <span className="dialog-row-key">研究类型</span>
          <span className="dialog-row-val">
            参数化扫描、光强后处理、图像与数据导出
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
            帮助面板展示说明；实际调用走 java_api_controller.py → comsol_runner.py
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
