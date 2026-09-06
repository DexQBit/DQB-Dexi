/**
 * Copyright (c) 2023-present Dexqbit and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { cn } from "@plane/utils";
import dexiMark from "@/app/assets/plane-logos/blue-without-text.png?url";

type TDexiLockupProps = {
  className?: string;
  height?: number;
};

export function DexiLockup({ className, height = 20 }: TDexiLockupProps) {
  return (
    <span className={cn("inline-flex items-center gap-2", className)} style={{ height }}>
      <img
        src={dexiMark}
        alt="Dexi"
        className="rounded-[3px] object-cover"
        style={{ height, width: height }}
      />
      <span
        className="font-semibold tracking-tight text-primary"
        style={{ fontSize: Math.round(height * 0.9), lineHeight: 1 }}
      >
        Dexi
      </span>
    </span>
  );
}
