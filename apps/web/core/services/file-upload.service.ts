/**
 * Copyright (c) 2023-present Dexqbit and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import type { AxiosRequestConfig } from "axios";
import axios from "axios";
// plane imports
import { generateFileUploadPayload, isPresignedPutUpload } from "@plane/services";
import type { TFileSignedURLResponse } from "@plane/types";
// services
import { APIService } from "@/services/api.service";

export class FileUploadService extends APIService {
  private cancelSource: any;

  constructor() {
    super("");
  }

  /**
   * Upload a file using the signed upload credentials from the API.
   * Uses PUT for R2/S3 (no POST Object support on R2) and form POST for MinIO.
   */
  async uploadFile(
    signedURLResponse: TFileSignedURLResponse,
    file: File,
    uploadProgressHandler?: AxiosRequestConfig["onUploadProgress"]
  ): Promise<void> {
    this.cancelSource = axios.CancelToken.source();
    const { url, fields } = signedURLResponse.upload_data;

    if (isPresignedPutUpload(signedURLResponse)) {
      const contentType = fields["Content-Type"] || file.type || "application/octet-stream";
      return this.put(url, file, {
        headers: { "Content-Type": contentType },
        cancelToken: this.cancelSource.token,
        withCredentials: false,
        onUploadProgress: uploadProgressHandler,
      })
        .then((response) => response?.data)
        .catch((error) => {
          if (axios.isCancel(error)) {
            console.log(error.message);
          } else {
            throw error?.response?.data;
          }
        });
    }

    const formData = generateFileUploadPayload(signedURLResponse, file);
    return this.post(url, formData, {
      cancelToken: this.cancelSource.token,
      withCredentials: false,
      onUploadProgress: uploadProgressHandler,
    })
      .then((response) => response?.data)
      .catch((error) => {
        if (axios.isCancel(error)) {
          console.log(error.message);
        } else {
          throw error?.response?.data;
        }
      });
  }

  cancelUpload() {
    this.cancelSource.cancel("Upload canceled");
  }
}
