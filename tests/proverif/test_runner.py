import unittest
from experiments.proverif.run import judge, parse_results


class RunnerTests(unittest.TestCase):
    def test_parse_realistic_true_and_false_query_formats(self):
        output = '''RESULT not attacker(secretCommand[]) is true.
RESULT event(accepted(c,e,s,m)) ==> event(sent(c,e,s,m)) is true.
RESULT inj-event(accepted(c,e,s,m)) ==> inj-event(sent(c,e,s,m)) is false.
RESULT not event(accepted_any) is false.
RESULT not event(accepted_both) is false.
'''
        results = parse_results(output)
        expected = {'secrecy':True,'authentication':True,'injective_authentication':False,
                    'acceptance_unreachable':False,'both_acceptances_unreachable':False}
        self.assertTrue(judge(expected,results,0)[0])

    def test_unknown_is_not_false_and_not_success(self):
        results = parse_results('RESULT not attacker(secretCommand[]) cannot be proved.')
        self.assertIsNone(results['secrecy']['observed'])
        self.assertFalse(judge({'secrecy':False},results,0)[0])

    def test_zero_exit_without_queries_is_not_success(self):
        self.assertFalse(judge({'secrecy':True},parse_results('No queries'),0)[0])

    def test_incomplete_and_timeout_and_exit_error(self):
        parsed = parse_results('RESULT not attacker(secretCommand[]) is true.')
        self.assertFalse(judge({'secrecy':True,'authentication':True},parsed,0)[0])
        self.assertFalse(judge({'secrecy':True},parsed,1)[0])
        self.assertFalse(judge({'secrecy':True},parsed,0,True)[0])

    def test_conflicting_lines_fail(self):
        with self.assertRaises(ValueError):
            parse_results('RESULT not attacker(secretCommand[]) is true.\nRESULT not attacker(secretCommand[]) is false.')

    def test_unrecognized_result_is_not_silently_skipped(self):
        with self.assertRaises(ValueError):
            parse_results('RESULT unexpected_property is true.')


if __name__ == '__main__':
    unittest.main()
