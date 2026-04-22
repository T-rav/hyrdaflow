// Synthesized example — structure inspired by functional-error-handling patterns.
// See ATTRIBUTION.md for provenance note.
package com.example.result;

import com.example.result.Success;
import com.example.result.Failure;

public abstract class Result<T> {
    public abstract boolean isSuccess();

    public static <T> Result<T> success(T value) {
        return new Success<>(value);
    }

    public static <T> Result<T> failure(String message) {
        return new Failure<>(message);
    }
}
