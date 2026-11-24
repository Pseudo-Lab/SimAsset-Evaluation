// Match Python/Pydantic length limits; never cut an IME composition or an emoji in half.
export const codePointLength = value => [...String(value)].length;
export const invalidUnicode = value => /\u0000|[\uD800-\uDFFF]/u.test(value);
export const searchText = value => String(value).normalize('NFC').toLowerCase();
