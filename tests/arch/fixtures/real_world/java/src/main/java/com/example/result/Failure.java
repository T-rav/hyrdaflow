// Synthesized example — structure inspired by functional-error-handling patterns.
package com.example.result;

public class Failure<T> extends Result<T> {
    private final String message;

    public Failure(String message) {
        this.message = message;
    }

    @Override
    public boolean isSuccess() {
        return false;
    }

    public String getMessage() {
        return message;
    }
}
