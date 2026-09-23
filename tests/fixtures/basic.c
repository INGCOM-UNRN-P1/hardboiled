/* Programa sin periféricos: funciones, globales, bucles y recursión. */
#include "hardboiled.h"

int counter = 3; /* .data */
int results[4];  /* .bss */

int square(int x)
{
    return x * x; /* @square_body */
}

int sum_squares(int n)
{
    int total = 0; /* @sum_first */
    for (int i = 1; i <= n; i++) {
        total += square(i); /* @sum_call */
    }
    return total; /* @sum_return */
}

int factorial(int n)
{
    if (n <= 1) {
        return 1;
    }
    return n * factorial(n - 1); /* @fact_recurse */
}

int main(void)
{
    int a = sum_squares(counter); /* @main_first */
    results[0] = a;               /* @main_store */

    int b = factorial(5); /* @main_fact */
    results[1] = b;
    return a + b; /* 14 + 120 = 134 */
}
