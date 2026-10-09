# Differentiation: recognising the rule and writing the solution

Course-note adaptation of OpenStax, Calculus Volume 1, sections 3.3 and 3.6.
Source: https://openstax.org/books/calculus-volume-1/pages/3-3-differentiation-rules
Source: https://openstax.org/books/calculus-volume-1/pages/3-6-the-chain-rule
These are public course examples, not Paul's personal notes. Retrieved 4 October 2026.

## Basic rules and tangent lines
For a differentiable power, d(x^n)/dx = n*x^(n-1); constants differentiate to zero. Differentiate sums term by term. Example 3.21: f(x)=2*x^5+7 gives f'(x)=10*x^4. Checkpoint 3.14 asks for the derivative of 2*x^3-6*x^2+3.
For a tangent at x=a, first find (a,f(a)), then m=f'(a), and write y-f(a)=m*(x-a). Example 3.22: f(x)=x^2-4*x+6 at a=1 gives point (1,3), slope -2, and y=-2*x+5. A function value is not a slope.
For a product, (f*g)'=f'*g+f*g'. Example 3.23 supplies f(2)=3, f'(2)=-4, g(2)=1, g'(2)=6; hence (f*g)'(2)=14. Multiplying the two derivatives is a trap.

## Composition and powers
The chain rule requires g differentiable at x and f differentiable at g(x): (f(g(x)))'=f'(g(x))*g'(x). Recognise a function inside another. Write the inner and outer functions first, differentiate the outer while retaining its argument, multiply by the inner derivative, then simplify. Never substitute a derivative as the outer argument.
Example 3.48: h(x)=1/(3*x^2+1)^2=(3*x^2+1)^(-2). Its derivative is -2*(3*x^2+1)^(-3)*6*x = -12*x/(3*x^2+1)^3. The inner derivative must not disappear. Checkpoint 3.34 asks for the derivative of (2*x^3+2*x-1)^4.
Example 3.49: h(x)=sin(x)^3 gives h'(x)=3*sin(x)^2*cos(x); the cube is outside the sine.

## A tangent using the chain rule
Example 3.50: h(x)=1/(3*x-5)^2 at x=2. The point is (2,1). Rewrite as (3*x-5)^(-2), so h'(x)=-6/(3*x-5)^3 and h'(2)=-6. Therefore y-1=-6*(x-2), or y=-6*x+13. The original function excludes x=5/3.
Practice adaptations may change coefficients or evaluation points, but must preserve the recognition cue and show the new solution. Clearly label these as generated variations, not course examples.
