import type { DoctorReport } from "../lib/parseDoctorReport";
import { MarkdownContent } from "./MarkdownContent";
import { Icon } from "./Icon";

function formatTime(ts: number): string {
  return new Date(ts).toLocaleTimeString("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

interface DoctorDiagnosisCardProps {
  report: DoctorReport | null;
  /** 原始文本：解析失败时降级为 Markdown */
  rawText: string;
  bridgeOk: boolean;
  time?: number;
}

function ListBlock({
  title,
  variant,
  items,
}: {
  title: string;
  variant: "error" | "warning" | "info";
  items: string[];
}) {
  if (items.length === 0) return null;
  return (
    <section className={`doctor-diagnosis__block doctor-diagnosis__block--${variant}`}>
      <h4 className="doctor-diagnosis__block-title">{title}</h4>
      <ul className="doctor-diagnosis__list">
        {items.map((item, i) => (
          <li key={`${variant}-${i}`} className="doctor-diagnosis__list-item">
            {item}
          </li>
        ))}
      </ul>
    </section>
  );
}

export function DoctorDiagnosisCard({
  report,
  rawText,
  bridgeOk,
  time,
}: DoctorDiagnosisCardProps) {
  const pass = Boolean(report && bridgeOk && report.outcome === "pass");
  const toneClass = !report
    ? "doctor-diagnosis--unknown"
    : pass
      ? "doctor-diagnosis--ok"
      : "doctor-diagnosis--fail";

  return (
    <div className={`assistant-msg-body doctor-diagnosis ${toneClass}`}>
      <div className="doctor-diagnosis__head">
        <div className="doctor-diagnosis__title-row">
          <span className="doctor-diagnosis__icon" aria-hidden>
            <Icon name="health" size={16} />
          </span>
          <h3 className="doctor-diagnosis__title">环境诊断</h3>
          {report && (
            <span
              className={`doctor-diagnosis__badge ${
                pass ? "doctor-diagnosis__badge--pass" : "doctor-diagnosis__badge--fail"
              }`}
            >
              {pass ? "通过" : "未通过"}
            </span>
          )}
        </div>
        {time != null && (
          <span className="doctor-diagnosis__time">{formatTime(time)}</span>
        )}
      </div>

      {!report && (
        <div className="doctor-diagnosis__markdown md-content">
          <MarkdownContent content={rawText} />
        </div>
      )}

      {report && (
        <div className="doctor-diagnosis__body">
          {report.backendStatusLine && (
            <p className="doctor-diagnosis__lead">{report.backendStatusLine}</p>
          )}

          <ListBlock title="错误" variant="error" items={report.errors} />
          <ListBlock title="警告" variant="warning" items={report.warnings} />
          <ListBlock title="详情" variant="info" items={report.infos} />

          {report.outcome === "pass" && report.errors.length === 0 && (
            <p className="doctor-diagnosis__hint">
              配置正常时可开始建模。若修改了 <code>.env</code>，可再次执行环境诊断确认。
            </p>
          )}
        </div>
      )}
    </div>
  );
}
