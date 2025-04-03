import pytest
from number_guessing import check_guess

def test_correct_guess():
    assert check_guess(5, 5) == "Congratulations! You guessed it!"

def test_low_guess():
    assert check_guess(3, 5) == "Higher!"

def test_high_guess():
    assert check_guess(7, 5) == "Lower!"

if __name__ == "__main__":
    pytest.main()
