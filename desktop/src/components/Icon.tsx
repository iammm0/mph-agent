import { createElement, type HTMLAttributes } from "react";

export type IconStyle = "bold" | "broken" | "bulk" | "linear" | "outline" | "twotone";

export interface IconProps extends Omit<HTMLAttributes<HTMLSpanElement>, "color"> {
  name: string;
  type?: IconStyle;
  size?: number | string;
  color?: string;
}

/** Iconsax 封装：网站 HTML 与桌面 React 都使用同一套 `<iconsax-icon>` 名称。 */
export function Icon({
  name,
  type = "linear",
  size = 18,
  color = "currentColor",
  className,
  ...rest
}: IconProps) {
  return (
    <span className={className ? `ix-icon ${className}` : "ix-icon"} {...rest}>
      {createElement("iconsax-icon", {
        name,
        type,
        size: String(size),
        color,
      })}
    </span>
  );
}
