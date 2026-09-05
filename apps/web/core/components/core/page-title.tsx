/**
 * Copyright (c) 2023-present Dexqbit and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect } from "react";

type PageHeadTitleProps = {
  title?: string;
  description?: string;
};

export function PageHead(props: PageHeadTitleProps) {
  const { title } = props;

  useEffect(() => {
    if (title) {
      document.title = title ?? "Dexi | Simple, extensible project management by Dexqbit.";
    }
  }, [title]);

  return null;
}
