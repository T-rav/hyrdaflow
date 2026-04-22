// Synthesized example — structure inspired by functional-error-handling patterns.
package com.example.result;

public class Success<T> extends Result<T> {
    private final T value;

    public Success(T value) {
        this.value = value;
    }

    @Override
    public boolean isSuccess() {
        return true;
    }

    public T getValue() {
        return value;
    }
}
