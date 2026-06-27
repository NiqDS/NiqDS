/** Errors that map cleanly to an HTTP status. Thrown anywhere, handled centrally. */
export class HttpError extends Error {
  constructor(
    public readonly status: number,
    message: string,
    public readonly code: string,
  ) {
    super(message);
    this.name = 'HttpError';
  }
}

export const badRequest = (msg: string, code = 'bad_request') =>
  new HttpError(400, msg, code);
export const unauthorized = (msg = 'Unauthorized', code = 'unauthorized') =>
  new HttpError(401, msg, code);
export const forbidden = (msg = 'Forbidden', code = 'forbidden') =>
  new HttpError(403, msg, code);
export const notFound = (msg = 'Not found', code = 'not_found') =>
  new HttpError(404, msg, code);
