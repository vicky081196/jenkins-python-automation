import random

def check_guess(guess, number):
    """Checks if the guessed number is correct, too high, or too low."""
    if guess < number:
        return "High!"
    elif guess > number:
        return "Lower!"
    else:
        return "Congratulations! You guessed it!"

def play_game():
    """Main function to play the guessing game."""
    number = random.randint(1, 10)
    attempts = 5

    print("Welcome to the Guessing Game!")
    print("I'm thinking of a number between 1 and 10.")
    print(f"You have {attempts} attempts to guess it.")

    for attempt in range(attempts):
        try:
            guess = int(input("Enter your guess: "))
        except ValueError:
            print("Invalid input! Please enter a number.")
            continue

        result = check_guess(guess, number)
        print(result)

        if result == "Congratulations! You guessed it!":
            break

        remaining_attempts = attempts - attempt - 1
        if remaining_attempts > 0:
            print(f"You have {remaining_attempts} attempts left.")
        else:
            print("No attempts left. You lost!")

    print(f"The number was: {number}")
    print("Thanks for playing!")

if __name__ == "__main__":
    play_game()
